"""Web routes. Every page needs a signed-in member of a family (except sign-in and onboarding);
every POST needs the session's CSRF token and, when the browser sends one, our own Origin."""

from __future__ import annotations

import contextlib
import hmac
import logging
import time
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from sprout import ai, auth, coloring, sheets, studio
from sprout.config import Settings
from sprout.db import Database
from sprout.families import Families, FamilyError
from sprout.store import IDEA_STATUS, MACHINES, RATINGS, Files, NotFound, QuotaExceeded, Store

log = logging.getLogger(__name__)
HERE = Path(__file__).parent
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "frame-ancestors 'none'; form-action 'self' https://accounts.google.com; base-uri 'none'; object-src 'none'"
)
PUBLIC = {
    "/login",
    "/auth/callback",
    "/dev-login",
    "/healthz",
    "/sw.js",
    "/manifest.webmanifest",
    "/offline",
    "/privacy",
    "/terms",
}
NO_FAMILY_OK = {"/welcome", "/logout", "/admin", "/family/switch", "/privacy", "/terms"}


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class App:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        settings.check()
        self.s = settings
        self.db = Database(settings.data_dir / "sprout.db")
        self.files = Files(settings.data_dir / "files", settings.family_quota_bytes)
        self.families = Families(self.db)
        self.sessions = auth.Sessions(self.db, settings.session_idle_seconds, settings.session_max_seconds)
        self.http = http or httpx.AsyncClient()
        self.studio = studio.Studio(settings.studio_url, settings.studio_token, self.http)
        self.kinds = sheets.available(self.studio)
        self.ai = ai.Assistant(settings, self.http, self.studio)
        self.env = Environment(
            loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html"])
        )
        self.env.globals.update(RATINGS=RATINGS, MACHINES=MACHINES, IDEA_STATUS=IDEA_STATUS, KINDS=self.kinds)
        self.cookie = "__Host-sprout" if settings.secure_cookies else "sprout_session"

    # -- helpers -------------------------------------------------------------------
    def page(self, request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
        st = request.state
        store: Store | None = getattr(st, "store", None)
        html = self.env.get_template(name).render(
            request=request,
            me=st.session.email if st.session else None,
            csrf=st.session.csrf if st.session else "",
            role=getattr(st, "role", None),
            family=getattr(st, "family", None),
            path=request.url.path,
            my_families=self.families.of(st.session.email) if st.session else [],
            is_admin=bool(st.session and self.s.is_admin(st.session.email)),
            children=store.children() if store else [],
            **ctx,
        )
        return self._secure(HTMLResponse(html, status))

    @staticmethod
    def _secure(r: Response) -> Response:
        r.headers.update(
            {
                "Content-Security-Policy": CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
                "Cache-Control": "private, no-store",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            }
        )
        return r

    def message(
        self, request: Request, status: int, title: str, message: str, link: str = "/"
    ) -> HTMLResponse:
        return self.page(request, "message.html", status, title=title, message=message, link=link)

    async def form(self, request: Request):
        origin = request.headers.get("origin")
        if origin and origin not in (self.s.origin, "null"):
            raise HTTPException(403, "Cross-site request refused.")
        f = await request.form(max_part_size=self.s.max_upload_bytes + 1024)
        if not hmac.compare_digest(str(f.get("csrf", "")).encode(), request.state.session.csrf.encode()):
            raise HTTPException(403, "The form expired. Go back, reload the page and try again.")
        return f

    @staticmethod
    def actor(request: Request) -> str:
        return request.state.session.email

    @staticmethod
    def store(request: Request) -> Store:
        return request.state.store

    def need_owner(self, request: Request) -> None:
        if request.state.role != "owner":
            raise HTTPException(403, "Only the family's owners can do that.")

    def child_or_none(self, request: Request, raw) -> dict | None:
        cid = _int(raw)
        return self.store(request).child(cid) if cid else None

    # -- sign-in -------------------------------------------------------------------
    async def login(self, request: Request) -> Response:
        rt = auth.safe_return_to(request.query_params.get("next"))
        if self.s.dev_login_email:
            return self.page(request, "login.html", dev=True, next=rt, open_signup=self.s.open_signup)
        flow = self.sessions.start_login(rt)
        if not flow:
            raise HTTPException(429, "Too many sign-ins in progress. Try again in a few minutes.")
        url = auth.authorization_url(self.s.google_client_id, self.s.public_base_url + "/auth/callback", flow)
        return self.page(request, "login.html", dev=False, google_url=url, open_signup=self.s.open_signup)

    async def callback(self, request: Request) -> Response:
        flow = self.sessions.take_login(request.query_params.get("state"))
        code = request.query_params.get("code")
        if not flow or not code:
            return self.message(
                request, 400, "Sign-in expired", "That sign-in link expired. Please try again.", "/login"
            )
        try:
            tok = await auth.exchange_code(
                self.http,
                self.s.google_client_id,
                self.s.google_client_secret,
                self.s.public_base_url + "/auth/callback",
                code,
                flow.verifier,
            )
            email, verified = auth.validate_id_token(tok, self.s.google_client_id, flow.nonce, time.time())
        except auth.LoginError as e:
            return self.message(request, e.status, "Sign-in failed", e.message, "/login")
        if not verified:
            return self.message(
                request, 403, "Email not verified", "Your Google email isn't verified.", "/login"
            )
        return self._signed_in(request, email, flow.return_to)

    def _signed_in(self, request: Request, email: str, return_to: str) -> Response:
        self.families.accept_pending(email)
        fams = self.families.of(email)
        if not fams and not (self.s.is_admin(email) or self.s.open_signup):
            self.db.audit(None, email, "login.refused")
            return self.message(
                request,
                403,
                "Sprout is invite-only for now",
                f"{email} isn't part of a family yet. Ask a family owner to invite this address.",
                "/login",
            )
        sid, _ = self.sessions.create(email, fams[0]["id"] if fams else None)
        self.db.audit(fams[0]["id"] if fams else None, email, "login")
        r = RedirectResponse(return_to if fams else "/welcome", 303)
        r.set_cookie(
            self.cookie,
            sid,
            max_age=self.s.session_max_seconds,
            httponly=True,
            secure=self.s.secure_cookies,
            samesite="lax",
            path="/",
        )
        return r

    async def dev_login(self, request: Request) -> Response:
        if not (self.s.dev_login_email and self.s.is_local):
            raise HTTPException(404, "Not found")
        email = (request.query_params.get("as") or self.s.dev_login_email).lower()
        return self._signed_in(request, email, auth.safe_return_to(request.query_params.get("next")))

    async def logout(self, request: Request) -> Response:
        await self.form(request)
        self.sessions.delete(request.cookies.get(self.cookie))
        r = RedirectResponse("/login", 303)
        r.delete_cookie(self.cookie, path="/")
        return r

    def can_create_family(self, email: str) -> bool:
        """Admins always; with open sign-up, anyone who doesn't already own a family."""
        return self.s.is_admin(email) or (self.s.open_signup and self.families.owned_count(email) == 0)

    async def welcome(self, request: Request) -> Response:
        """Signed in but no family: create one (when allowed) or wait for an invite."""
        error = None
        if request.method == "POST":
            f = await self.form(request)
            if not self.can_create_family(self.actor(request)):
                raise HTTPException(
                    403, "You can't create another family. Ask an owner to invite you instead."
                )
            if f.get("agree") != "on":
                return self.page(
                    request,
                    "welcome.html",
                    error="Please accept the terms and privacy policy.",
                    can_create=True,
                )
            try:
                fid = self.families.create(str(f.get("name", "")), self.actor(request), self.actor(request))
                self.sessions.set_family(request.state.session, fid)
                return RedirectResponse("/family", 303)
            except FamilyError as e:
                error = str(e)
        if request.state.family and request.query_params.get("new") is None:
            return RedirectResponse("/", 303)
        return self.page(
            request, "welcome.html", error=error, can_create=self.can_create_family(self.actor(request))
        )

    async def switch_family(self, request: Request) -> Response:
        f = await self.form(request)
        fid = _int(f.get("family_id"))
        if not self.families.role(fid, self.actor(request)):
            raise HTTPException(403, "You're not in that family.")
        self.sessions.set_family(request.state.session, fid)
        return RedirectResponse("/", 303)

    # -- family settings -----------------------------------------------------------
    async def family(self, request: Request) -> Response:
        fid, error = request.state.family["id"], None
        if request.method == "POST":
            f = await self.form(request)
            action = f.get("action")
            if action == "leave":
                try:
                    self.families.leave(fid, self.actor(request))
                except FamilyError as e:
                    return self.message(request, 400, "Can't leave yet", str(e), "/family")
                return RedirectResponse("/", 303)
            self.need_owner(request)
            if action == "delete_family":
                if str(f.get("confirm", "")).strip() != request.state.family["name"]:
                    return self.message(
                        request, 400, "Not deleted", "Type the family's name exactly to confirm.", "/family"
                    )
                self.families.delete(fid, self.actor(request), self.files.root)
                r = RedirectResponse("/welcome", 303)
                return r
            try:
                if action == "rename":
                    self.families.rename(fid, str(f.get("name", "")), self.actor(request))
                elif action == "invite":
                    self.families.invite(
                        fid, str(f.get("email", "")), str(f.get("role", "member")), self.actor(request)
                    )
                elif action == "cancel_invite":
                    self.families.cancel_invite(fid, str(f.get("email", "")), self.actor(request))
                elif action == "remove_member":
                    self.families.remove_member(fid, str(f.get("email", "")), self.actor(request))
                elif action == "add_child":
                    self.store(request).add_child(
                        str(f.get("name", "")),
                        str(f.get("born", "")),
                        self.actor(request),
                        str(f.get("trace_name", "")),
                    )
                return RedirectResponse("/family", 303)
            except (FamilyError, ValueError) as e:
                error = str(e)
        return self.page(
            request,
            "family.html",
            members=self.families.members(fid),
            invites=self.families.invites(fid),
            error=error,
        )

    async def admin(self, request: Request) -> Response:
        if not self.s.is_admin(self.actor(request)):
            raise HTTPException(404, "Not found")
        error = None
        if request.method == "POST":
            f = await self.form(request)
            try:
                fid = self.families.create(str(f.get("name", "")), self.actor(request), self.actor(request))
                owner = str(f.get("owner_email", "")).strip()
                if owner and owner.lower() != self.actor(request):
                    self.families.invite(fid, owner, "owner", self.actor(request))
                    if f.get("leave") == "on":
                        self.families.remove_member(fid, self.actor(request), self.actor(request))
                return RedirectResponse("/admin", 303)
            except FamilyError as e:
                error = str(e)
        return self.page(request, "admin.html", families=self.families.all(), error=error)

    # -- family pages --------------------------------------------------------------
    async def home(self, request: Request) -> Response:
        st = self.store(request)
        return self.page(
            request, "home.html", requests=st.requests(5), stats=st.stats(), ai_ready=self.ai.ready
        )

    async def child(self, request: Request) -> Response:
        st = self.store(request)
        c = st.child(request.path_params["cid"])
        if request.method == "POST":
            f = await self.form(request)
            action = f.get("action")
            if action == "plan":
                st.update_child(
                    c["id"],
                    self.actor(request),
                    current_level=str(f.get("current_level", "")),
                    next_steps=str(f.get("next_steps", "")),
                )
            elif action == "profile":
                self.need_owner(request)
                try:
                    st.update_child(
                        c["id"],
                        self.actor(request),
                        name=str(f.get("name", "")),
                        born=str(f.get("born", "")),
                        trace_name=str(f.get("trace_name", "")),
                    )
                except ValueError as e:
                    return self.message(request, 400, "Couldn't save", str(e), f"/child/{c['id']}")
            elif action in ("feedback", "note"):
                rating = str(f.get("rating") or "")
                sheet_id = _int(f.get("sheet_id"))
                title = str(f.get("title", "")).strip()
                if sheet_id:
                    title = st.sheet(sheet_id)["title"]
                st.add_entry(
                    c["id"],
                    action,
                    title or ("How it went" if action == "feedback" else "Note"),
                    self.actor(request),
                    detail=str(f.get("detail", "")),
                    rating=rating if rating in RATINGS else None,
                    sheet_id=sheet_id,
                )
            return RedirectResponse(f"/child/{c['id']}", 303)
        return self.page(
            request,
            "child.html",
            child=c,
            entries=st.entries(c["id"]),
            recent_sheets=st.sheets(c["id"], 10),
            ideas=[i for i in st.ideas() if i["child_id"] == c["id"]],
        )

    async def make(self, request: Request) -> Response:
        return self.page(request, "make.html", child_id=request.query_params.get("child", ""))

    async def make_kind(self, request: Request) -> Response:
        kind = self.kinds.get(request.path_params["kind"])
        if not kind:
            raise HTTPException(404, "Unknown worksheet")
        st, error, values = self.store(request), None, {}
        child = self.child_or_none(request, request.query_params.get("child"))
        if request.method == "POST":
            f = await self.form(request)
            child = self.child_or_none(request, f.get("child_id"))
            names = {fl.name for fl in kind.fields}
            values = {k: v for k, v in f.items() if k in names}
            for fl in kind.fields:
                if fl.type == "bool" and fl.name not in values:
                    values[fl.name] = False
            try:
                params = kind.validate(values)
                title, pdf = await sheets.make(
                    kind,
                    params,
                    studio=self.studio,
                    child=child,
                    renders_today=st.sheets_since(sheets.STUDIO_KINDS, time.time() - 86400),
                    daily_cap=self.s.studio_family_daily_cap,
                )
            except sheets.InvalidParams as e:
                error = str(e)
            else:
                sid = st.add_sheet(
                    child["id"] if child else None,
                    kind.id,
                    title,
                    params,
                    pdf,
                    self.actor(request),
                    status="draft",
                )
                return RedirectResponse(f"/sheet/{sid}", 303)
        elif child and kind.id == "name_trace":
            values = {"name": child.get("trace_name") or child["name"]}
        return self.page(
            request,
            "make_kind.html",
            kind=kind,
            error=error,
            values=values,
            child_id=child["id"] if child else "",
        )

    async def sheet(self, request: Request) -> Response:
        st = self.store(request)
        s = st.sheet(request.path_params["sid"])
        if request.method == "POST":
            f = await self.form(request)
            if f.get("action") == "keep":
                st.keep_sheet(s["id"], self.actor(request), _int(f.get("child_id")))
            return RedirectResponse(f"/sheet/{s['id']}", 303)
        pdf = st.file(s["file"]).read_bytes()
        return self.page(
            request,
            "sheet.html",
            sheet=s,
            pages=sheets.page_count(pdf),
            child=st.child(s["child_id"]) if s["child_id"] else None,
            remake=s["kind"] in self.kinds,
            from_ask=request.query_params.get("from") == "ask",
        )

    async def sheet_pdf(self, request: Request) -> Response:
        st = self.store(request)
        s = st.sheet(request.path_params["sid"])
        fname = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in s["title"])[:60] + ".pdf"
        return self._secure(
            FileResponse(
                st.file(s["file"]),
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{fname}"'},
            )
        )

    async def sheet_png(self, request: Request) -> Response:
        st = self.store(request)
        s = st.sheet(request.path_params["sid"])
        n = request.path_params["page"]
        path = st.file(s["file"])
        cache = path.with_suffix(f".p{n}.png")
        if not cache.exists():
            cache.write_bytes(sheets.preview_png(path.read_bytes(), n))
        return self._secure(FileResponse(cache, media_type="image/png"))

    async def coloring_list(self, request: Request) -> Response:
        st, error = self.store(request), None
        if request.method == "POST":
            f = await self.form(request)
            try:
                if f.get("action") == "url":
                    src = str(f.get("url", ""))
                    data = await coloring.fetch_allowed(self.http, src, self.s.max_upload_bytes)
                else:
                    up, src = f.get("file"), ""
                    if not up or not getattr(up, "filename", ""):
                        raise coloring.ColoringError("Choose a file to upload.")
                    data = await up.read(self.s.max_upload_bytes + 1)
                pid = st.add_coloring(
                    str(f.get("title", "")),
                    str(f.get("tags", "")),
                    coloring.to_pdf(data, self.s.max_upload_bytes),
                    self.actor(request),
                    src,
                )
                return RedirectResponse(f"/coloring/{pid}", 303)
            except coloring.ColoringError as e:
                error = str(e)
        tag = request.query_params.get("tag")
        return self.page(
            request,
            "coloring.html",
            pages=st.coloring(tag),
            tag=tag,
            tags=st.tags(),
            error=error,
            hosts=", ".join(sorted(coloring.ALLOWED_HOSTS)),
        )

    async def coloring_one(self, request: Request) -> Response:
        st = self.store(request)
        p = st.coloring_page(request.path_params["pid"])
        if request.method == "POST":
            f = await self.form(request)
            child = self.child_or_none(request, f.get("child_id"))
            if child:
                sid = st.add_sheet(
                    child["id"],
                    "coloring",
                    p["title"],
                    {"coloring_id": p["id"]},
                    st.file(p["file"]).read_bytes(),
                    self.actor(request),
                )
                st.add_entry(
                    child["id"], "sheet", "Coloring: " + p["title"], self.actor(request), sheet_id=sid
                )
            return RedirectResponse(f"/coloring/{p['id']}?saved=1", 303)
        return self.page(request, "coloring_one.html", p=p, saved=request.query_params.get("saved"))

    async def coloring_file(self, request: Request) -> Response:
        st = self.store(request)
        p = st.coloring_page(request.path_params["pid"])
        path = st.file(p["file"])
        if request.path_params["fmt"] == "png":
            cache = path.with_suffix(".thumb.png")
            if not cache.exists():
                cache.write_bytes(sheets.preview_png(path.read_bytes(), 0, 600))
            return self._secure(FileResponse(cache, media_type="image/png"))
        if request.path_params["fmt"] != "pdf":
            raise HTTPException(404, "Not found")
        return self._secure(
            FileResponse(
                path,
                media_type="application/pdf",
                headers={"Content-Disposition": 'inline; filename="coloring.pdf"'},
            )
        )

    async def ask(self, request: Request) -> Response:
        st, result = self.store(request), None
        if request.method == "POST":
            f = await self.form(request)
            text = str(f.get("text", "")).strip()
            child = self.child_or_none(request, f.get("child_id"))
            if not text:
                result = {"status": "failed", "message": "Type what you would like."}
            else:
                rid = st.add_request(child["id"] if child else None, text, self.actor(request))
                result = await self.ai.fulfil(st, rid, text, child, self.actor(request))
                if result.get("sheet_id"):
                    return RedirectResponse(f"/sheet/{result['sheet_id']}?from=ask", 303)
        return self.page(
            request,
            "ask.html",
            result=result,
            requests=st.requests(20),
            ai_ready=self.ai.ready,
            can_draw=self.ai.can_draw,
            child_id=request.query_params.get("child", ""),
        )

    async def ideas(self, request: Request) -> Response:
        st, error = self.store(request), None
        if request.method == "POST":
            f = await self.form(request)
            try:
                if f.get("action") == "status":
                    st.set_idea_status(
                        _int(f.get("idea_id")) or 0, str(f.get("status", "")), self.actor(request)
                    )
                else:
                    child = self.child_or_none(request, f.get("child_id"))
                    st.add_idea(
                        str(f.get("title", "")),
                        str(f.get("detail", "")),
                        str(f.get("machine", "other")),
                        child["id"] if child else None,
                        self.actor(request),
                    )
                return RedirectResponse("/ideas", 303)
            except ValueError as e:
                error = str(e)
        return self.page(request, "ideas.html", ideas=st.ideas(), error=error)

    async def policy(self, request: Request) -> Response:
        name = request.url.path.strip("/")
        return self.page(
            request,
            f"{name}.html",
            operator=self.s.operator_name or "the operator of this site",
            contact=self.s.contact_email,
            quota_mb=self.s.family_quota_bytes // (1024 * 1024),
        )

    # -- plumbing ------------------------------------------------------------------
    async def offline(self, request: Request) -> Response:
        return self.message(request, 200, "Offline", "You're offline. Connect and try again.")

    async def healthz(self, request: Request) -> Response:
        self.db.one("SELECT 1")
        return Response('{"status":"ok"}', media_type="application/json")

    async def static_root(self, request: Request) -> Response:
        name = request.url.path.lstrip("/")
        media = {"sw.js": "text/javascript", "manifest.webmanifest": "application/manifest+json"}[name]
        return FileResponse(HERE / "static" / name, media_type=media, headers={"Cache-Control": "no-cache"})

    def guard(self, handler):
        async def run(request: Request) -> Response:
            st = request.state
            st.session = self.sessions.get(request.cookies.get(self.cookie))
            st.family = st.role = st.store = None
            path = request.url.path
            if st.session:
                role = self.families.role(st.session.family_id, st.session.email)
                if role:
                    st.role, st.family = role, self.families.get(st.session.family_id)
                    st.store = Store(self.db, self.files, st.session.family_id)
                elif st.session.family_id is not None:  # removed from that family since sign-in
                    fams = self.families.of(st.session.email)
                    self.sessions.set_family(st.session, fams[0]["id"] if fams else None)
                    return RedirectResponse(path, 303)
            if path not in PUBLIC:
                if not st.session:
                    nxt = path + (f"?{request.url.query}" if request.url.query else "")
                    return RedirectResponse("/login?next=" + auth.safe_return_to(nxt), 303)
                if not st.family and path not in NO_FAMILY_OK:
                    return RedirectResponse("/welcome", 303)
            try:
                return await handler(request)
            except NotFound:
                raise HTTPException(404, "That isn't here (or belongs to another family).") from None
            except QuotaExceeded as e:
                raise HTTPException(413, str(e)) from None

        return run

    def asgi(self) -> Starlette:
        G, GP, P = ("GET",), ("GET", "POST"), ("POST",)
        r = lambda path, h, m=G: Route(path, self.guard(h), methods=list(m))
        routes = [
            r("/", self.home),
            r("/login", self.login),
            r("/auth/callback", self.callback),
            r("/dev-login", self.dev_login),
            r("/logout", self.logout, P),
            r("/welcome", self.welcome, GP),
            r("/family/switch", self.switch_family, P),
            r("/family", self.family, GP),
            r("/admin", self.admin, GP),
            r("/child/{cid:int}", self.child, GP),
            r("/make", self.make),
            r("/make/{kind}", self.make_kind, GP),
            r("/sheet/{sid:int}", self.sheet, GP),
            r("/sheet/{sid:int}.pdf", self.sheet_pdf),
            r("/sheet/{sid:int}/page/{page:int}.png", self.sheet_png),
            r("/coloring", self.coloring_list, GP),
            r("/coloring/{pid:int}", self.coloring_one, GP),
            r("/coloring/{pid:int}.{fmt}", self.coloring_file),
            r("/ask", self.ask, GP),
            r("/privacy", self.policy),
            r("/terms", self.policy),
            r("/ideas", self.ideas, GP),
            r("/offline", self.offline),
            Route("/healthz", self.healthz),
            Route("/sw.js", self.static_root),
            Route("/manifest.webmanifest", self.static_root),
            Mount("/static", StaticFiles(directory=HERE / "static"), name="static"),
        ]

        async def http_error(request: Request, exc: HTTPException) -> Response:
            for attr in ("session", "family", "role", "store"):
                if not hasattr(request.state, attr):
                    setattr(request.state, attr, None)
            return self.message(request, exc.status_code, "Something went wrong", str(exc.detail))

        @contextlib.asynccontextmanager
        async def lifespan(_app):
            yield
            await self.http.aclose()

        return Starlette(routes=routes, exception_handlers={HTTPException: http_error}, lifespan=lifespan)


def create_app() -> Starlette:
    from sprout.config import from_env

    logging.basicConfig(level=logging.INFO)
    return App(from_env()).asgi()
