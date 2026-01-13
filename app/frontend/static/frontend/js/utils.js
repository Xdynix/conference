(function () {
  "use strict";

  /**
   * Creates a URL builder function from a template with placeholders.
   *
   * Placeholders use the format `__PARAM_NAME__` (uppercase with double underscores).
   * The returned function accepts positional arguments in the same order as paramNames.
   *
   * @param {string} template - URL template with placeholders.
   * @param {...string} paramNames - Parameter names matching placeholders (in order).
   * @returns {function(...string): string} Function that builds the URL.
   *
   * @example
   * const getConference = urlTemplate(
   *   "/api/v1/conferences/__CONFERENCE_NAME__/",
   *   "conference_name"
   * );
   * getConference("icse-2025")  // "/api/v1/conferences/icse-2025/"
   *
   * @example
   * const getPaper = urlTemplate(
   *   "/api/v1/conferences/__CONFERENCE_NAME__/papers/__PAPER_UID__/",
   *   "conference_name", "paper_uid"
   * );
   * getPaper("icse-2025", "abc-123")  // "/api/v1/conferences/icse-2025/papers/abc-123/"
   */
  function urlTemplate(template, ...paramNames) {
    return (...values) => {
      let url = template;
      paramNames.forEach((name, i) => {
        url = url.replace(`__${name.toUpperCase()}__`, encodeURIComponent(values[i]));
      });
      return url;
    };
  }

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

  /**
   * Extracts the URL hash fragment and optionally clears it from the address bar.
   *
   * @param {boolean} [clear=true] - Whether to clear the hash from the URL.
   * @returns {string} The hash value without the leading "#", or empty string if none.
   */
  function extractUrlHash(clear = true) {
    const hash = window.location.hash.slice(1);
    if (hash && clear) {
      history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    return hash;
  }

  /**
   * Returns a safe redirect URL, validating that it's same-origin.
   *
   * @param {string|null} next - The requested redirect URL.
   * @param {string} fallback - The fallback URL if next is invalid or missing.
   * @returns {string} A safe same-origin URL to redirect to.
   */
  function safeRedirectUrl(next, fallback) {
    if (next) {
      try {
        const url = new URL(next, window.location.origin);
        if (url.origin === window.location.origin) {
          return url.pathname + url.search + url.hash;
        }
      } catch {
        // Invalid URL, ignore.
      }
    }
    return fallback;
  }

  window.urlTemplate = urlTemplate;
  window.mapErrors = mapErrors;
  window.getModelValue = getModelValue;
  window.setModelValue = setModelValue;
  window.extractUrlHash = extractUrlHash;
  window.safeRedirectUrl = safeRedirectUrl;
})();
