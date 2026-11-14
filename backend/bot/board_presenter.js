// Installed only in the bot's browser. Never captures the desktop or meeting UI.
(() => {
  if (window.__wilcoBoard) return;
  const canvas = document.createElement('canvas');
  canvas.width = 1280; canvas.height = 720;
  const ctx = canvas.getContext('2d');
  const original = navigator.mediaDevices?.getDisplayMedia?.bind(navigator.mediaDevices);
  let armed = false, stream = null, version = null, lastBoard = null, frameTimer = null;
  const color = (token, fallback) => getComputedStyle(document.documentElement).getPropertyValue(token).trim() || fallback;
  function wrap(text, x, y, width, lines) {
    const words = String(text || '').split(/\s+/); let line = '', count = 0;
    for (const word of words) {
      if (ctx.measureText(line + word).width > width && line) {
        ctx.fillText(line, x, y + count * 22); line = ''; count++;
        if (count === lines) return;
      }
      line += word + ' ';
    }
    if (count < lines) ctx.fillText(line, x, y + count * 22);
  }
  function draw(board) {
    lastBoard = board;
    version = board.version;
    const background = color('--background', 'white');
    const ink = color('--foreground', 'black');
    const primary = color('--primary', 'rebeccapurple');
    const surface = color('--card', 'white');
    const muted = color('--muted-foreground', 'dimgray');
    ctx.fillStyle = background; ctx.fillRect(0, 0, 1280, 720);
    ctx.fillStyle = ink; ctx.font = '600 30px sans-serif'; wrap(board.title, 36, 48, 1110, 1);
    ctx.font = '16px sans-serif'; ctx.fillStyle = muted;
    ctx.fillText('Wilco · Live meeting board · Version ' + board.version, 36, 80);
    const nodes = board.nodes || [], edges = board.edges || [];
    if (!nodes.length) { ctx.fillText('Describe what you want to put on the board.', 36, 150); return; }
    const minX = Math.min(...nodes.map(n => n.x)), minY = Math.min(...nodes.map(n => n.y));
    const maxX = Math.max(...nodes.map(n => n.x + 310)), maxY = Math.max(...nodes.map(n => n.y + 155));
    const scale = Math.min(1.2, 1200 / (maxX - minX), 560 / (maxY - minY));
    ctx.save(); ctx.translate(40, 120); ctx.scale(scale, scale); ctx.translate(-minX, -minY);
    const byId = new Map(nodes.map(n => [n.id, n]));
    ctx.strokeStyle = primary; ctx.lineWidth = 2;
    for (const edge of edges) {
      const a = byId.get(edge.source), b = byId.get(edge.target); if (!a || !b) continue;
      const x1 = a.x + 310, y1 = a.y + 75, x2 = b.x, y2 = b.y + 75;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      const angle = Math.atan2(y2-y1, x2-x1);
      ctx.beginPath(); ctx.moveTo(x2, y2);
      ctx.lineTo(x2-12*Math.cos(angle-0.4), y2-12*Math.sin(angle-0.4));
      ctx.moveTo(x2,y2); ctx.lineTo(x2-12*Math.cos(angle+0.4), y2-12*Math.sin(angle+0.4)); ctx.stroke();
    }
    for (const node of nodes) {
      ctx.fillStyle = surface; ctx.beginPath(); ctx.roundRect(node.x, node.y, 310, 155, 12); ctx.fill(); ctx.stroke();
      ctx.fillStyle = muted; ctx.font = '14px sans-serif'; ctx.fillText(node.kind + (node.origin === 'ai' ? ' · AI draft' : ''), node.x+16, node.y+25);
      ctx.fillStyle = ink; ctx.font = '600 19px sans-serif'; wrap(node.title, node.x+16, node.y+54, 278, 2);
      ctx.fillStyle = muted; ctx.font = '16px sans-serif'; wrap(node.text, node.x+16, node.y+108, 278, 2);
    }
    ctx.restore();
  }
  window.__wilcoBoard = {
    draw,
    arm(board) { draw(board); armed = true; },
    stop() { armed = false; clearInterval(frameTimer); frameTimer = null; if (stream) stream.getTracks().forEach(t => t.stop()); stream = null; },
    state() { return {armed, active: !!stream?.getVideoTracks().some(t => t.readyState === 'live'), version}; },
    preview() { return canvas.toDataURL('image/png'); },
  };
  if (original) navigator.mediaDevices.getDisplayMedia = async (...args) => {
    if (!armed) return original(...args);
    armed = false;
    if (stream) stream.getTracks().forEach(t => t.stop());
    clearInterval(frameTimer);
    stream = canvas.captureStream(5);
    // Continue painting for late WebRTC subscribers, even when the board is idle.
    frameTimer = setInterval(() => {
      if (!stream?.getVideoTracks().some(t => t.readyState === 'live')) {
        clearInterval(frameTimer); frameTimer = null; return;
      }
      if (lastBoard) draw(lastBoard);
    }, 500);
    const track = stream.getVideoTracks()[0];
    track.contentHint = 'detail';
    track.addEventListener('ended', () => { clearInterval(frameTimer); frameTimer = null; });
    const settings = track.getSettings.bind(track);
    track.getSettings = () => ({...settings(), displaySurface:'browser', logicalSurface:true});
    return stream;
  };
})();
