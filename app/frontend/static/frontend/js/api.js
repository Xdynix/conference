(function () {
  "use strict";

  const SAFE_METHODS = ["get", "head", "options"];

  let pendingMutations = 0;

  const api = axios.create({
    timeout: 30_000,
    headers: {
      "Content-Type": "application/json",
    },
    xsrfCookieName: APP.config.csrf.cookie,
    xsrfHeaderName: APP.config.csrf.header,
  });

  api.interceptors.request.use(function (config) {
    if (!SAFE_METHODS.includes(config.method?.toLowerCase())) {
      pendingMutations++;
    }
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
