// A deliberately strict, minimal DOM for the reviewer-interface render tests.
//
// WHY NOT A REAL BROWSER
// ----------------------
// The suite must run with no browser, no network and no extra dependency, so the
// renderers in `claimguard/review/ui/static/render.mjs` take the document as an
// argument and are exercised here against this shim instead.
//
// WHY IT IS SEALED
// ----------------
// A shim that silently accepted `node.innerHTML = "<script>…</script>"` would
// make the injection test vacuous. Every element created here is `Object.seal`ed
// and this module is loaded as an ES module (strict mode), so assigning a
// property the shim does not declare — `innerHTML`, `outerHTML`, `srcdoc`, a
// `on*` handler — throws a TypeError instead of quietly doing nothing. The only
// ways to add content are `append` (a node) and `textContent` (text), which is
// exactly the safe subset the renderers must restrict themselves to.

class TextNode {
  constructor(data) {
    this.nodeType = 3;
    this.data = String(data);
    Object.seal(this);
  }
}

class ElementNode {
  constructor(tagName) {
    this.nodeType = 1;
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.listeners = [];
    Object.seal(this);
  }

  append(...kids) {
    for (const kid of kids) this.children.push(kid);
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  addEventListener(type, handler) {
    this.listeners.push([String(type), handler]);
  }

  get textContent() {
    return this.children.map((kid) => (kid.nodeType === 3 ? kid.data : kid.textContent)).join("");
  }

  set textContent(value) {
    this.children = [new TextNode(value)];
  }
}

/** A document-like object with only the two factories the renderers may use. */
export function makeDocument() {
  return {
    createElement: (tagName) => new ElementNode(tagName),
    createTextNode: (data) => new TextNode(data),
  };
}

const escapeText = (value) =>
  String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const escapeAttribute = (value) => escapeText(value).replace(/"/g, "&quot;");

/** Serialize a node tree the way a browser's `outerHTML` would. */
export function serialize(node) {
  if (node.nodeType === 3) return escapeText(node.data);
  const tag = node.tagName.toLowerCase();
  const attributes = Object.entries(node.attributes)
    .map(([name, value]) => ` ${name}="${escapeAttribute(value)}"`)
    .join("");
  const className = node.className ? ` class="${escapeAttribute(node.className)}"` : "";
  const body = node.children.map(serialize).join("");
  return `<${tag}${className}${attributes}>${body}</${tag}>`;
}

/** Every element name in the tree, so a caller can assert what was created. */
export function elementNames(node) {
  if (node.nodeType === 3) return [];
  return [node.tagName.toLowerCase(), ...node.children.flatMap(elementNames)];
}
