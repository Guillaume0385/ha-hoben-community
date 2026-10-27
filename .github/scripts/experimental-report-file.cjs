"use strict";
// A deliberately stand-alone, secretless reader for the ONLY public JSON file.
// Never follow symlinks or expose unverified arbitrary bytes to Actions.
const fs = require("node:fs");
const MAX_BYTES = 2 * 1024 * 1024;
const need = ok => { if (!ok) throw Error("invalid_public_report"); };
function snapshot(file, maximum = MAX_BYTES) {
  need(Number.isSafeInteger(maximum) && maximum > 0 && maximum <= MAX_BYTES);
  const before = fs.lstatSync(file);
  need(before.isFile() && !before.isSymbolicLink());
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const stat = fs.fstatSync(fd);
    need(stat.isFile() && stat.dev === before.dev && stat.ino === before.ino &&
      stat.size > 0 && stat.size <= maximum);
    const data = Buffer.alloc(stat.size);
    for (let offset = 0; offset < data.length;) {
      const count = fs.readSync(fd, data, offset, data.length - offset, offset);
      need(count > 0);
      offset += count;
    }
    need(fs.readSync(fd, Buffer.alloc(1), 0, 1, data.length) === 0 &&
      fs.fstatSync(fd).size === stat.size);
    return data;
  } finally { fs.closeSync(fd); }
}
module.exports = {snapshot, MAX_BYTES};
