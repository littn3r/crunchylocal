// Format bottom dialogue while preserving positioned signs and other typesetting.
function formatAssDialogue(source, factor = 1, bottomPercent = null) {
  if (!Number.isFinite(factor) || factor <= 0) factor = 1;
  if (bottomPercent !== null && (!Number.isFinite(bottomPercent) || bottomPercent < 0)) bottomPercent = null;
  if (factor === 1 && bottomPercent === null) return source;
  const fieldsOf = (value, count) => {
    const parts = value.split(',');
    return [...parts.slice(0, count - 1), parts.slice(count - 1).join(',')];
  };
  const lines = source.split(/\r?\n/);
  const styles = new Map();
  let section = '';
  let styleFields = [];
  let playResY = 288;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*\[/.test(line)) section = line.trim().toLowerCase();
    else if (section === '[script info]' && /^\s*PlayResY:/i.test(line)) playResY = Number(line.split(':')[1]) || playResY;
    else if (section.startsWith('[v4') && /^\s*Format:/i.test(line)) styleFields = line.slice(line.indexOf(':') + 1).split(',').map((part) => part.trim().toLowerCase());
    else if (section.startsWith('[v4') && /^\s*Style:/i.test(line) && styleFields.length) {
      const values = fieldsOf(line.slice(line.indexOf(':') + 1).trim(), styleFields.length);
      const nameIndex = styleFields.indexOf('name');
      if (values.length === styleFields.length && nameIndex >= 0) styles.set(values[nameIndex].trim().toLowerCase(), { index: i, values, fields: styleFields });
    }
  }
  section = '';
  let eventFields = [];
  const copies = new Map();
  const marginV = bottomPercent === null ? null : String(Math.round(playResY * bottomPercent / 100));
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*\[/.test(line)) section = line.trim().toLowerCase();
    else if (section === '[events]' && /^\s*Format:/i.test(line)) eventFields = line.slice(line.indexOf(':') + 1).split(',').map((part) => part.trim().toLowerCase());
    else if (section === '[events]' && /^\s*Dialogue:/i.test(line) && eventFields.length) {
      const values = fieldsOf(line.slice(line.indexOf(':') + 1).trim(), eventFields.length);
      const styleIndex = eventFields.indexOf('style');
      const textIndex = eventFields.indexOf('text');
      if (values.length !== eventFields.length || styleIndex < 0 || textIndex < 0) continue;
      const style = styles.get(values[styleIndex].trim().toLowerCase());
      if (!style) continue;
      const text = values[textIndex];
      if (/\\(?:pos|move)\s*\(/i.test(text) || /\\p[1-9]/i.test(text)) continue;
      const override = [...text.matchAll(/\\an([1-9])\b/gi)].at(-1);
      const alignIndex = style.fields.indexOf('alignment');
      const alignment = Number(override?.[1] || style.values[alignIndex] || 2);
      if (![1, 2, 3].includes(alignment)) continue;
      const originalName = style.values[style.fields.indexOf('name')].trim();
      const scaledName = `CL_Dialogue_${originalName}`;
      const sizeIndex = style.fields.indexOf('fontsize');
      if (sizeIndex < 0 || !Number.isFinite(Number(style.values[sizeIndex]))) continue;
      if (!copies.has(style.index)) {
        const scaled = [...style.values];
        scaled[style.fields.indexOf('name')] = scaledName;
        scaled[sizeIndex] = String(Math.round(Number(scaled[sizeIndex]) * factor * 100) / 100);
        const marginIndex = style.fields.indexOf('marginv');
        if (marginIndex >= 0 && marginV !== null) scaled[marginIndex] = marginV;
        copies.set(style.index, `Style: ${scaled.join(',')}`);
      }
      values[styleIndex] = scaledName;
      const eventMarginIndex = eventFields.indexOf('marginv');
      if (eventMarginIndex >= 0 && Number(values[eventMarginIndex]) && marginV !== null) values[eventMarginIndex] = marginV;
      values[textIndex] = text.replace(/\\fs(\d+(?:\.\d+)?)/gi, (_, size) => `\\fs${Math.round(Number(size) * factor * 100) / 100}`);
      lines[i] = `Dialogue: ${values.join(',')}`;
    }
  }
  return lines.flatMap((line, index) => copies.has(index) ? [line, copies.get(index)] : [line]).join('\n');
}
function scaleAssDialogue(source, factor) { return formatAssDialogue(source, factor); }
if (typeof window !== 'undefined') window.scaleAssDialogue = scaleAssDialogue;
if (typeof window !== 'undefined') window.formatAssDialogue = formatAssDialogue;
if (typeof module !== 'undefined') module.exports = { scaleAssDialogue, formatAssDialogue };
