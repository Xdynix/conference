(function () {
  "use strict";

  /**
   * Creates a Cloudflare Turnstile widget Alpine.js component.
   *
   * When Turnstile is disabled or not configured, the component becomes a no-op that
   * immediately reports ready with no token required.
   *
   * Requires a container element with x-ref matching the `ref` option (default:"cf-turnstile").
   * The Turnstile widget will be rendered inside this container.
   *
   * @param {object} [options={}] - Configuration options.
   * @param {string} [options.action=''] - Action name for Turnstile analytics.
   * @param {string} [options.ref='cf-turnstile'] - Alpine x-ref name for the widget container.
   * @returns {object} Alpine.js component data object.
   *
   * @example
   * <div x-data="cfTurnstileWidget({ action: 'login' })">
   *   <div x-ref="cf-turnstile"></div>
   *   <button :disabled="!cfTurnstileReady()" @click="submit()">Submit</button>
   * </div>
   */
  function cfTurnstileWidget({action = "", ref = "cf-turnstile"} = {}) {
    return {
      token: "",
      error: "",
      widgetId: null,

      cfTurnstileReady() {
        return !this.isEnabled() || !!this.token;
      },

      isEnabled() {
        return APP.cfTurnstile.enabled;
      },

      init() {
        if (!this.isEnabled()) {
          return;
        }

        this.$nextTick(() => {
          this.render();
        });
      },

      render() {
        const container = this.$refs[ref];
        if (!container || !window.turnstile) {
          return;
        }

        this.widgetId = turnstile.render(container, {
          sitekey: APP.cfTurnstile.siteKey,
          action,
          callback: (token) => {
            this.token = token;
            this.error = "";
          },
          "error-callback": (errorCode) => {
            this.token = "";
            this.error = errorCode || "verification-failed";
          },
          "expired-callback": () => {
            this.token = "";
          },
        });
      },

      cfTurnstileReset() {
        this.token = "";
        this.error = "";
        if (this.widgetId !== null && window.turnstile) {
          turnstile.reset(this.widgetId);
        }
      },

      /**
       * Returns request config with the Turnstile token header.
       * Use with axios: api.post(url, data, this.cfRequestConfig())
       *
       * @returns {object} Axios request config with Turnstile header.
       */
      cfRequestConfig() {
        if (!this.isEnabled() || !this.token) {
          return {};
        }
        return {
          headers: {
            [APP.cfTurnstile.responseHeader]: this.token,
          },
        };
      },
    };
  }

  window.cfTurnstileWidget = cfTurnstileWidget;
})();
