/* Native FigJam objects only. No generated JavaScript is executed. */
const API = "__API_ORIGIN__";
let connection = null;
let pendingAck = null;
let polling = false;
let stopped = false;
let dirty = true;
let remoteVersion = 0;
figma.showUI(__html__, { width: 360, height: 420, themeColors: true });
// Observe only this page; documentchange would load every page in large files.
const page = figma.currentPage;
page.on("nodechange", () => { dirty = true; });

function owned(type) {
  return figma.currentPage.findAll(node => (!type || node.type === type) &&
    node.getPluginData("wilco_connection") === connection.connection_id);
}
function describe(node) {
  const saved = JSON.parse(node.getPluginData("wilco_data"));
  const text = node.text.characters;
  const split = text.indexOf("\n");
  return { ...saved, title: split < 0 ? text : text.slice(0, split), text: split < 0 ? "" : text.slice(split + 1), x: node.x, y: node.y, locked: node.locked };
}
function same(left, right) {
  return !!left && !!right && left.title === right.title && left.text === right.text &&
    Math.abs(left.x - right.x) < .5 && Math.abs(left.y - right.y) < .5 && !!left.locked === !!right.locked;
}
function nativeSnapshot() {
  const points = owned("SHAPE_WITH_TEXT");
  const ids = new Map(points.map(node => [node.id, node.getPluginData("wilco_id")]));
  return { nodes: points.map(describe), edges: owned("CONNECTOR").map(node => ({
    id: node.getPluginData("wilco_id"), source: ids.get(node.connectorStart.endpointNodeId), target: ids.get(node.connectorEnd.endpointNodeId),
  })).filter(edge => edge.source && edge.target) };
}
function mark(node, value) {
  node.setPluginData("wilco_connection", connection.connection_id);
  node.setPluginData("wilco_id", value.id);
  node.setPluginData("wilco_data", JSON.stringify(value));
}
function applySnapshot(delivery) {
  const baseline = delivery.baseline;
  const snapshot = delivery.snapshot;
  const byId = new Map(owned().map(node => [node.getPluginData("wilco_id"), node]));
  const before = new Map(baseline.nodes.map(node => [node.id, node]));
  const after = new Map(snapshot.nodes.map(node => [node.id, node]));
  const edgeBefore = new Map(baseline.edges.map(edge => [edge.id, edge]));
  const edgeAfter = new Map(snapshot.edges.map(edge => [edge.id, edge]));
  // Check the entire edit before changing anything. Human edits to a point
  // being modified are conflicts; unrelated native objects stay untouched.
  for (const [id, previous] of before) {
    const desired = after.get(id);
    if (desired && same(previous, desired)) continue;
    const existing = byId.get(id);
    if (!existing || !same(describe(existing), previous) || existing.locked) return "conflict";
  }
  for (const value of snapshot.nodes) {
    const existing = byId.get(value.id);
    if (!before.has(value.id) && existing && !same(describe(existing), value)) return "conflict";
  }
  for (const [id, previous] of edgeBefore) {
    const desired = edgeAfter.get(id);
    if (desired && desired.source === previous.source && desired.target === previous.target) continue;
    const native = byId.get(id);
    if (!native || native.locked || native.connectorStart.endpointNodeId !== byId.get(previous.source)?.id ||
        native.connectorEnd.endpointNodeId !== byId.get(previous.target)?.id) return "conflict";
  }
  for (const value of snapshot.nodes) {
    const previous = before.get(value.id);
    if (previous && same(previous, value)) continue;
    let node = byId.get(value.id);
    if (!node) {
      node = figma.createShapeWithText();
      node.shapeType = "ROUNDED_RECTANGLE";
      node.resize(300, 180);
      byId.set(value.id, node);
    }
    node.text.fontName = { family: "Inter", style: "Regular" };
    node.text.fontSize = 16;
    node.text.characters = value.title + (value.text ? "\n" + value.text : "");
    node.x = value.x; node.y = value.y;
    mark(node, value);
  }
  const afterEdges = new Set(snapshot.edges.map(edge => edge.id));
  for (const edge of baseline.edges) {
    if (!afterEdges.has(edge.id)) byId.get(edge.id)?.remove();
  }
  for (const edge of snapshot.edges) {
    const previous = edgeBefore.get(edge.id);
    if (previous && previous.source === edge.source && previous.target === edge.target) continue;
    const start = byId.get(edge.source), end = byId.get(edge.target);
    if (!start || !end) throw new Error("Missing connector point");
    const node = byId.get(edge.id) || figma.createConnector();
    node.connectorStart = { endpointNodeId: start.id, magnet: "AUTO" };
    node.connectorEnd = { endpointNodeId: end.id, magnet: "AUTO" };
    node.connectorEndStrokeCap = "ARROW_LINES";
    mark(node, edge);
  }
  for (const [id] of before) if (!after.has(id)) byId.get(id)?.remove();
  figma.commitUndo();
  return "applied";
}
async function request(path, body, auth = true) {
  const response = await fetch(API + "/api/figjam/bridge" + path, {
    method: "POST", headers: { "Content-Type": "application/json", ...(auth ? { Authorization: "Bridge " + connection.token } : {}) },
    body: JSON.stringify(body || {}),
  });
  if (!response.ok) {
    const error = new Error(response.status === 409 ? "The board is busy. Waiting for the current command." : "Connection paused. Check Wilco and reconnect if needed.");
    error.status = response.status;
    throw error;
  }
  return response.json();
}
async function tick() {
  if (!connection || polling || stopped) return;
  if (figma.currentPage.id !== page.id) {
    figma.ui.postMessage({status:"Return to the connected FigJam page to continue."});
    return;
  }
  polling = true;
  try {
    if (pendingAck) {
      await request("/deliveries/" + pendingAck.id + "/ack", { state: pendingAck.state });
      pendingAck = null;
    }
    const result = await request("/poll");
    remoteVersion = result.version;
    if (result.delivery) {
      const delivery = result.delivery;
      let state;
      const saved = JSON.parse(figma.currentPage.getPluginData("wilco_last_delivery") || "null");
      if (saved?.id === delivery.id) state = saved.state;
      else if (Date.now() >= Date.parse(delivery.expires_at)) state = "failed";
      else {
        try { state = applySnapshot(delivery); } catch { state = "failed"; }
        figma.currentPage.setPluginData("wilco_last_delivery", JSON.stringify({id: delivery.id, state}));
      }
      pendingAck = {id: delivery.id, state};
      await request("/deliveries/" + delivery.id + "/ack", {state});
      pendingAck = null;
      dirty = true;
      figma.ui.postMessage({ status: state === "applied" ? "Updated in FigJam. Share this file using Figma’s Share button." : "A point changed while Wilco was working. Check the board and ask again." });
    } else if (dirty) {
      const graph = nativeSnapshot();
      const synced = await request("/snapshot", { ...graph, expected_version: remoteVersion, title: "Meeting board" });
      remoteVersion = synced.version;
      dirty = false;
    }
  } catch (error) {
    figma.ui.postMessage({status: error.message});
    if (error.status === 401 || error.status === 410) { connection = null; stopped = true; }
  } finally { polling = false; }
}
figma.ui.onmessage = async message => {
  if (message.type === "disconnect") {
    if (connection) { try { await request('/disconnect'); } catch {} }
    stopped = true; connection = null; figma.closePlugin(); return;
  }
  if (message.type !== "pair" || polling) return;
  try {
    const key = message.file_url.match(/^https:\/\/(?:www\.)?figma\.com\/(?:board|file)\/([a-zA-Z0-9]+)/)?.[1];
    if (!key || (figma.fileKey && figma.fileKey !== key)) throw new Error("Open the FigJam file matching that link before connecting.");
    await figma.loadFontAsync({family: "Inter", style: "Regular"});
    connection = await request("/pair", { code: message.code.trim(), file_key: key }, false);
    stopped = false; dirty = true;
    figma.ui.postMessage({status: "Connected. Say ‘Wilco, draw a flow’ in your meeting.", connected: true});
    await tick();
  } catch (error) { figma.ui.postMessage({status: error.message}); }
};
setInterval(tick, 750);
