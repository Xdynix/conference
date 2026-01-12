(function () {
  "use strict";

  /**
   * Maps API validation errors to field-keyed error messages.
   *
   * Extracts the field path from `loc` after stripping common prefixes like "body" and
   * "payload". Nested paths are joined with dots. Multiple errors for the same field
   * are joined with a space. For example:
   *   [{loc: ["body", "payload", "password"], msg: "Too short."},
   *    {loc: ["body", "payload", "password"], msg: "Too common."}]
   * becomes:
   *   {password: "Too short. Too common."}
   *
   * And nested fields:
   *   [{loc: ["body", "payload", "profile", "given_name"], msg: "Required."}]
   * becomes:
   *   {"profile.given_name": "Required."}
   *
   * @param {Array<{loc: string[], msg: string}>} details - API error details array.
   * @returns {Object<string, string>} Field-keyed error messages.
   */
  function mapErrors(details) {
    const prefixes = new Set(["body", "payload"]);
    const result = {};
    for (const error of details || []) {
      const loc = error.loc || [];
      const fieldParts = loc.filter((part) => !prefixes.has(part));
      const field = fieldParts.join(".") || "_form";
      if (result[field]) {
        result[field] += " " + error.msg;
      } else {
        result[field] = error.msg;
      }
    }
    return result;
  }

  /**
   * Gets a value from an object using a dot-separated path.
   *
   * @param {object} obj - The object to read from.
   * @param {string} path - Dot-separated path, e.g. "form.email".
   * @returns {*} The value at the path, or undefined if not found.
   */
  function getModelValue(obj, path) {
    return path.split(".").reduce((o, key) => o?.[key], obj);
  }

  /**
   * Sets a value on an object using a dot-separated path.
   *
   * @param {object} obj - The object to modify.
   * @param {string} path - Dot-separated path, e.g. "form.email".
   * @param {*} value - The value to set.
   */
  function setModelValue(obj, path, value) {
    const keys = path.split(".");
    const last = keys.pop();
    const target = keys.reduce((o, key) => o[key], obj);
    target[last] = value;
  }

  window.mapErrors = mapErrors;
  window.getModelValue = getModelValue;
  window.setModelValue = setModelValue;
})();
