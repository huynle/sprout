# Contributing to Sprout

Thanks for helping! A few things to know:

- **License.** Sprout is licensed under the GNU Affero General Public License v3.0 or later
  (see [LICENSE](LICENSE)). If you run a modified Sprout as a service for others, the AGPL requires
  you to offer them your modified source.
- **Contributor License Agreement.** Before a pull request can be merged you need to agree to the
  [CLA](CLA.md) (a bot asks on your first pull request). It lets the maintainer also offer Sprout
  under other terms, such as commercial licenses, which helps keep the project sustainable. You keep
  the copyright in your work.
- **No personal data.** Never commit real children's names, birthdays, photos or family exports.
  Tests and examples use invented families.
- **Before opening a pull request:** `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`.
- **Security issues:** please don't open a public issue; contact the maintainer privately.
