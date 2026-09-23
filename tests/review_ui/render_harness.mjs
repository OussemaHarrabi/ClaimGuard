// Test harness: run the shipped renderers over a payload and report what a
// browser would show.
//
// Usage: node render_harness.mjs <payload.json>
//
// The payload is a JSON object with any of the keys the renderers accept
// (`finding`, `counts`, `error`, `legend`, `decisions`, `queue`, `run`). The
// harness prints one JSON object on stdout:
//
//   { "html": "<div>…</div>", "elements": ["div", "span", …], "text": "…" }
//
// `html` is the serialized subtree (escaped the way a browser escapes text),
// `elements` is every element name that was created, and `text` is the visible
// text. A `<script>` element appearing in `elements`, or an unescaped `<script`
// in `html`, is an injection. If a renderer reaches for `innerHTML` the sealed
// shim throws and this harness exits non-zero — also a failure.

import { readFileSync } from "node:fs";

import * as render from "../../claimguard/review/ui/static/render.mjs";

import { elementNames, makeDocument, serialize } from "./dom_shim.mjs";

const payload = JSON.parse(readFileSync(process.argv[2], "utf8"));
const doc = makeDocument();
const root = doc.createElement("div");

if (payload.finding) {
  root.append(render.renderFinding(doc, payload.finding.record, payload.finding.options || {}));
}
if (payload.counts) root.append(render.renderCounts(doc, payload.counts));
if (payload.error) {
  root.append(
    render.renderApiError(doc, payload.error.status, payload.error.body, payload.error.context),
  );
}
if (payload.notice) {
  root.append(render.renderNotice(doc, payload.notice.message, payload.notice.kind, payload.notice.detail));
}
if (payload.legend) root.append(render.renderLegend(doc));
if (payload.decisions) root.append(render.renderDecisions(doc, payload.decisions));
if (payload.queue) {
  root.append(render.renderQueueItems(doc, payload.queue.items, () => {}));
  root.append(render.renderClaims(doc, payload.queue.claims, () => {}));
}
if (payload.run) root.append(render.renderRunHeader(doc, payload.run));

process.stdout.write(
  JSON.stringify({ html: serialize(root), elements: elementNames(root), text: root.textContent }),
);
