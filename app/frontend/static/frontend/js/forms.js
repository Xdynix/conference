(function () {
  "use strict";

  /**
   * Maps API validation errors to field-keyed error messages.
   *
   * Extracts the field name from the last element of `loc` (which has prefixes
   * like "body", "payload"). For example:
   *   [{loc: ["body", "payload", "username"], msg: "Required"}]
   * becomes:
   *   {username: "Required"}
   *
   * @param {Array<{loc: string[], msg: string}>} details - API error details array.
   * @returns {Object<string, string>} Field-keyed error messages.
   */
  function mapErrors(details) {
    const result = {};
    for (const error of details || []) {
      const field = error.loc?.[error.loc.length - 1] || "_form";
      if (!result[field]) {
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
