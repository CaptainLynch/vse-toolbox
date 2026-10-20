export function attachPolicyDigest(payload, digest) {
  if (Object.prototype.hasOwnProperty.call(payload, 'expectedConfigDigest')) {
    throw new TypeError('payload already owns expectedConfigDigest');
  }
  return typeof digest === 'string' && digest.length > 0
    ? { ...payload, expectedConfigDigest: digest } : { ...payload };
}

export function isPolicyDigestConflict(error) {
  if (error === null || typeof error !== 'object' || error.status !== 422) return false;
  const fields = error.fields;
  if (fields === null || typeof fields !== 'object' || Array.isArray(fields)) return false;
  if (Object.prototype.hasOwnProperty.call(fields, 'expectedConfigDigest')) return true;
  const keys = Object.keys(fields);
  return keys.length === 1 && keys[0] === 'request'
    && fields.request === '绑定已发生变化，请刷新配置后重试';
}
