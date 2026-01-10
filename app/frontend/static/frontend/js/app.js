(function () {
  "use strict";

  if (!window.APP?.csrf?.token || !window.APP?.csrf?.header) {
    throw new Error("APP.csrf not configured.");
  }

  const api = axios.create({
    timeout: 30_000,
    headers: {
      "Content-Type": "application/json",
    }
  });

  api.interceptors.request.use(function (config) {
    config.headers[APP.csrf.header] = APP.csrf.token;
    return config;
  });

  window.api = api;
})();
