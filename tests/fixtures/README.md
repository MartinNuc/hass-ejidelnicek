# Test fixtures

The `canteen_*.html` files are trimmed, anonymised snapshots of real public
E-jídelníček menu pages from five distinct real-world deployments of the
system. They exist to pin down real-world variation in the payload shape
(single vs. multiple menu options, long serving windows, placeholder-only
menus, differing `posunDne`/day-count combinations) that the parser must
handle correctly.

Each file has been trimmed to the minimum HTML needed to reproduce the
`ejidelnicek.setJidelnicek(...)` call the real page embeds in a `<script>`
block — no navigation chrome, styling, or other page furniture, and no
hostnames or other identifying markers. The five source deployments cannot be
identified from these files.

No personal data is present. These are all **public, unauthenticated** views
of the menu, and the E-jídelníček system fills those views with
`"objednavka": 0` (no order placed) and `"cena": "0.00"` (no price shown) for
every menu option, regardless of the underlying data — this has been verified
for every fixture in this directory. Czech dish, soup, and dessert names are
preserved as-is; they are public menu text and carry no personal data.

`ajax_authenticated.json` is different: it is entirely hand-written and
synthetic, not derived from any real account or response. It mirrors the
shape of the authenticated AJAX response (which does carry order and account
data) so tests can exercise that code path, but every value in it is
invented. It deliberately omits identifying fields such as `jmeno`, `cislo`,
`vs`, and `loginEmail` from the `stravnik` object.

`not_ejidelnicek.html` is a hand-written, plausible-looking but unrelated
Czech canteen login page containing no `setJidelnicek` payload, used to test
that the parser correctly rejects pages with no menu data.
