// Trusted main only. Validate final CMS bytes, then seal that bounded snapshot
// to the sole ciphertext upload path. Never log input, ASN.1 or crypto errors.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const child = require('node:child_process');
const MAX_BYTES = 64 * 1024 * 1024;
const need = fact => { if (!fact) throw Error('invalid_ciphertext'); };
const oid = (item, hex) => item?.tag === 0x06 && item.value.equals(Buffer.from(hex,'hex'));

// A small strict DER reader for this fixed OpenSSL CMS profile. No indefinite
// lengths, high tags, unbounded child lists, trailing bytes or optional payloads.
function item(bytes, offset=0) {
  const start = offset;
  need(offset+2 <= bytes.length);
  const tag = bytes[offset++];
  need((tag & 0x1f) !== 0x1f);
  let length = bytes[offset++];
  if (length & 0x80) {
    const count = length & 0x7f;
    need(count >= 1 && count <= 4 && offset+count <= bytes.length && bytes[offset] !== 0);
    length = 0;
    for (let n=0;n<count;n++) length = length*256 + bytes[offset++];
    need(length >= 128);
  }
  need(length <= MAX_BYTES && offset+length <= bytes.length);
  return {tag,value:bytes.subarray(offset,offset+length),
    raw:bytes.subarray(start,offset+length),end:offset+length};
}
function children(parent, tag, max=8) {
  need(parent?.tag === tag);
  const result = [];
  for (let offset=0;offset<parent.value.length;) {
    need(result.length < max);
    const next = item(parent.value,offset);
    result.push(next); offset = next.end;
  }
  return result;
}
function exact(parent, tag, count) {
  const result = children(parent,tag,count);
  need(result.length === count);
  return result;
}
function sha256Algorithm(algorithm) {
  const parts = children(algorithm,0x30,2);
  need((parts.length === 1 || parts.length === 2) &&
    oid(parts[0],'608648016503040201') &&
    (parts.length === 1 || parts[1].tag === 0x05 && parts[1].value.length === 0));
}
function oaep(algorithm) {
  const [identifier,params] = exact(algorithm,0x30,2);
  need(oid(identifier,'2a864886f70d010107'));
  const fields = children(params,0x30,3);
  need(fields.length === 2 || fields.length === 3);
  sha256Algorithm(exact(fields[0],0xa0,1)[0]);
  const [mgf,hash] = exact(exact(fields[1],0xa1,1)[0],0x30,2);
  need(oid(mgf,'2a864886f70d010108'));
  sha256Algorithm(hash);
  if (fields.length === 3) {
    const [source,label] = exact(exact(fields[2],0xa2,1)[0],0x30,2);
    need(oid(source,'2a864886f70d010109') && label.tag === 0x04 && label.value.length === 0);
  }
}
function recipient(file, fingerprint) {
  const stat = fs.lstatSync(file);
  need(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 16384);
  const pem = fs.readFileSync(file,'ascii');
  need(!pem.includes('PRIVATE KEY') &&
    (pem.match(/BEGIN CERTIFICATE/g)||[]).length === 1 &&
    (pem.match(/END CERTIFICATE/g)||[]).length === 1);
  const cert = new crypto.X509Certificate(pem);
  need(crypto.createHash('sha256').update(cert.raw).digest('hex') === fingerprint &&
    cert.publicKey.asymmetricKeyType === 'rsa' &&
    cert.publicKey.asymmetricKeyDetails.modulusLength >= 3072 &&
    Date.parse(cert.validFrom) <= Date.now() && Date.parse(cert.validTo) >= Date.now()+3600000);
  const root = item(cert.raw);
  need(root.end === cert.raw.length);
  const [tbs] = exact(root,0x30,3);
  const fields = children(tbs,0x30,16);
  const offset = fields[0].tag === 0xa0 ? 1 : 0;
  const serial = fields[offset], issuer = fields[offset+2];
  need(serial.tag === 0x02 && issuer.tag === 0x30);
  return {pem,serial:serial.raw,issuer:issuer.raw,
    keyBytes:Math.ceil(cert.publicKey.asymmetricKeyDetails.modulusLength/8)};
}
function validate(bytes, cert) {
  need(bytes.length > 0 && bytes.length <= MAX_BYTES);
  const root = item(bytes);
  need(root.end === bytes.length);
  const [contentType,wrapped] = exact(root,0x30,2);
  need(oid(contentType,'2a864886f70d0109100117'));
  const envelope = exact(wrapped,0xa0,1)[0];
  // No originator, authenticated/unauthenticated attributes or extra recipients
  // can carry unvalidated material in the upload.
  const [version,recipients,encrypted,mac] = exact(envelope,0x30,4);
  need(version.tag === 0x02 && version.value.equals(Buffer.from([0])));
  const [keyTransport] = exact(recipients,0x31,1);
  const [keyVersion,identity,algorithm,key] = exact(keyTransport,0x30,4);
  need(keyVersion.tag === 0x02 && keyVersion.value.equals(Buffer.from([0])));
  const [issuer,serial] = exact(identity,0x30,2);
  need(issuer.raw.equals(cert.issuer) && serial.raw.equals(cert.serial));
  oaep(algorithm);
  need(key.tag === 0x04 && key.value.length === cert.keyBytes);
  const [type,cipher,payload] = exact(encrypted,0x30,3);
  need(oid(type,'2a864886f70d010701'));
  const [cipherId,parameters] = exact(cipher,0x30,2);
  need(oid(cipherId,'60864801650304012e'));
  const [nonce,icvLength] = exact(parameters,0x30,2);
  need(nonce.tag === 0x04 && nonce.value.length === 12 &&
    icvLength.tag === 0x02 && icvLength.value.equals(Buffer.from([16])) &&
    payload.tag === 0x80 && payload.value.length > 0 &&
    mac.tag === 0x04 && mac.value.length === 16);
}
function snapshot(file) {
  const before = fs.lstatSync(file);
  need(before.isFile() && !before.isSymbolicLink());
  const fd = fs.openSync(file,fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const stat = fs.fstatSync(fd);
    need(stat.isFile() && stat.dev === before.dev && stat.ino === before.ino &&
      stat.size > 0 && stat.size <= MAX_BYTES);
    const bytes = Buffer.alloc(stat.size);
    for (let offset=0;offset<bytes.length;) {
      const count = fs.readSync(fd,bytes,offset,bytes.length-offset,offset);
      need(count > 0); offset += count;
    }
    need(fs.readSync(fd,Buffer.alloc(1),0,1,bytes.length) === 0 &&
      fs.fstatSync(fd).size === stat.size);
    return bytes;
  } finally { fs.closeSync(fd); }
}
function prepare(temp, certificate, fingerprint) {
  const root = path.resolve(temp);
  const sourceDirectory = path.join(root,'hoben-experimental-exports');
  need(fs.realpathSync(root) === root);
  const parent = fs.lstatSync(sourceDirectory);
  need(parent.isDirectory() && !parent.isSymbolicLink());
  const bytes = snapshot(path.join(sourceDirectory,'captures.cms'));
  const cert = recipient(certificate,fingerprint);
  validate(bytes,cert);
  // Public-key validation cannot authenticate the candidate's GCM tag or prove
  // that its payload bytes were encrypted. Seal every candidate byte again in
  // trusted main, so even a structurally valid plaintext payload cannot leak.
  const staging = fs.mkdtempSync(path.join(root,'hoben-experimental-seal-'));
  fs.chmodSync(staging,0o700);
  try {
    const input = path.join(staging,'candidate.cms');
    const pem = path.join(staging,'recipient.pem');
    const output = path.join(staging,'sealed.cms');
    fs.writeFileSync(input,bytes,{mode:0o600,flag:'wx'});
    fs.writeFileSync(pem,cert.pem,{mode:0o600,flag:'wx'});
    const fd = fs.openSync(output,'wx',0o600);
    try {
      child.execFileSync('/usr/bin/openssl',['cms','-encrypt','-binary','-aes-256-gcm',
        '-outform','DER','-in',input,'-out','/dev/fd/3','-recip',pem,
        '-keyopt','rsa_padding_mode:oaep','-keyopt','rsa_oaep_md:sha256'],
      {env:{PATH:'/usr/bin:/bin'},stdio:['ignore','ignore','ignore',fd],timeout:30000});
    } finally { fs.closeSync(fd); }
    const sealed = snapshot(output);
    validate(sealed,cert);
    const destination = path.join(root,'hoben-experimental-ciphertext');
    fs.mkdirSync(destination,{mode:0o700});
    fs.writeFileSync(path.join(destination,'captures.cms'),sealed,{mode:0o600,flag:'wx'});
  } finally { fs.rmSync(staging,{recursive:true,force:true}); }
}
module.exports = {prepare,MAX_BYTES};
