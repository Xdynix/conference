(function () {
  "use strict";

  if (!window.APP?.csrf?.token || !window.APP?.csrf?.header) {
    throw new Error("APP.csrf not configured.");
  }

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

  window.mapErrors = mapErrors;

  const SAFE_METHODS = ["get", "head", "options"];

  let pendingMutations = 0;

  const api = axios.create({
    timeout: 30_000,
    headers: {
      "Content-Type": "application/json",
    }
  });

  api.interceptors.request.use(function (config) {
    if (!SAFE_METHODS.includes(config.method?.toLowerCase())) {
      pendingMutations++;
    }
    config.headers[APP.csrf.header] = APP.csrf.token;
    return config;
  });

  api.interceptors.response.use(
    function (response) {
      if (!SAFE_METHODS.includes(response.config.method?.toLowerCase())) {
        pendingMutations--;
      }
      return response;
    },
    function (error) {
      if (!SAFE_METHODS.includes(error.config?.method?.toLowerCase())) {
        pendingMutations--;
      }
      return Promise.reject(error);
    }
  );

  window.addEventListener("beforeunload", function (e) {
    if (pendingMutations > 0) {
      e.preventDefault();
      return "";
    }
  });

  window.api = api;
})();
