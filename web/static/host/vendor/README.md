# Vendored frontend runtime

| File | Source | Version | License | SHA-256 of upstream file |
| --- | --- | --- | --- | --- |
| `preact-htm.js` | npm `htm@3.1.1`, `preact/standalone.module.js` | htm 3.1.1 (bundles Preact 10 + hooks) | htm Apache-2.0, Preact MIT | `72284e8e9079c87817145df1110f74e8a2aa040b2fc384922e18dfcb46fc1fd7` |

The file is the upstream build with one license comment line prepended; do
not edit it by hand. To upgrade, `npm pack htm@<version>`, copy
`package/preact/standalone.module.js` here with the same header, and update
this table.

Company PCs cannot reach public CDNs reliably, so the runtime ships inside the
package and the UI has no build step (decision 2026-10-01, see
`docs/PLUGIN_REFACTOR_PLAN_20261001.md`).
