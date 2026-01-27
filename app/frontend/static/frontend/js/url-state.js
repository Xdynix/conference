/**
 * URL State - Sync state with URL query parameters.
 *
 * Naming follows Python's `json` module: `loads`/`dumps` for pure string operations, with `sync`/`use` as wrappers for
 * browser integration.
 *
 * @example
 * // Type helpers
 * const { string, number, boolean, oneOf, arrayOf, setOf } = UrlState.types;
 *
 * const schema = {
 *   // String: any string value
 *   search: string({ default: '' }),
 *
 *   // Number: with optional min/max clamping
 *   page: number({ default: 1, min: 1, max: 100 }),
 *
 *   // Boolean: parses 1/0, true/false, yes/no; outputs 1/0
 *   active: boolean({ default: true }),
 *
 *   // OneOf: string enum constrained to allowed values
 *   sort: oneOf(['name', 'date', 'size'], { default: 'name' }),
 *
 *   // ArrayOf: order-sensitive list (e.g., column ordering)
 *   columns: arrayOf(oneOf(['id', 'name', 'date'], { default: '' }), {
 *     default: ['id', 'name'],
 *   }),
 *
 *   // SetOf: order-insensitive set (e.g., filter checkboxes)
 *   status: setOf(oneOf(['draft', 'published'], { default: '' }), {
 *     default: ['draft'],
 *   }),
 * };
 *
 * @example
 * // Alpine.js integration
 * function myComponent() {
 *   return {
 *     ...UrlState.use(schema),
 *     init() {
 *       this.initUrlState();
 *     },
 *     // Access: this.urlState.search, this.urlState.page, etc.
 *   };
 * }
 *
 * @example
 * // Core functions (framework-agnostic)
 * const state = UrlState.loads(schema, location.search);
 * const queryString = UrlState.dumps(schema, state);
 * UrlState.sync(schema, state); // Updates URL
 */
(function () {
  "use strict";

  /**
   * @template T
   * @typedef {object} FieldType
   * @property {(raw: string) => T | undefined} loads - Parse URL string to value, `undefined` if invalid
   * @property {(value: T) => string} dumps - Convert value to URL string
   * @property {(value: T) => boolean} isDefault - Check if value equals the default
   * @property {T} default - Default value when param is missing or invalid
   */
  // loads returns undefined (not throwing) to signal invalid input, allowing fallback to default.
  // isDefault is required so each type can define its own comparison (e.g., setOf is order-insensitive).

  /**
   * @typedef {Object<string, FieldType<*>>} Schema
   */

  const UrlState = {
    types: {
      /**
       * String type. Accepts any string value.
       *
       * @param {{default: string}} options
       * @returns {FieldType<string>}
       */
      string({default: defaultValue}) {
        return {
          loads: (raw) => raw,
          dumps: (value) => value,
          isDefault: (value) => value === defaultValue,
          default: defaultValue,
        };
      },

      /**
       * Integer type. Parses integer literals with optional min/max clamping.
       *
       * Only accepts integer format (e.g., "1", "-42", "0"). Rejects floats, scientific notation, and empty strings.
       * Min/max apply on load only; `dumps` does not clamp values.
       *
       * @param {{default: number, min?: number, max?: number}} options
       * @returns {FieldType<number>}
       */
      number({default: defaultValue, min, max}) {
        return {
          loads(raw) {
            if (!/^-?\d+$/.test(raw)) return undefined;
            const num = Number(raw);
            if (min !== undefined && num < min) return min;
            if (max !== undefined && num > max) return max;
            return num;
          },
          dumps: (value) => String(value),
          isDefault: (value) => value === defaultValue,
          default: defaultValue,
        };
      },

      /**
       * Boolean type. Parses common boolean representations, outputs "1"/"0".
       *
       * @param {{default: boolean}} options
       * @returns {FieldType<boolean>}
       */
      // Lenient input: accepts 1/0, true/false, yes/no (case-insensitive).
      // Strict output: always serializes to "1" or "0" for brevity.
      boolean({default: defaultValue}) {
        const truthy = ["1", "true", "yes"];
        const falsy = ["0", "false", "no"];
        return {
          loads(raw) {
            const lower = raw.toLowerCase();
            if (truthy.includes(lower)) return true;
            if (falsy.includes(lower)) return false;
            return undefined;
          },
          dumps: (value) => (value ? "1" : "0"),
          isDefault: (value) => value === defaultValue,
          default: defaultValue,
        };
      },

      /**
       * Enum type. Constrains value to a list of allowed strings.
       *
       * String-only since URL params are inherently strings. For numeric enums, use string representations:
       * `oneOf(["1", "2", "3"], ...)`.
       *
       * @param {string[]} allowed - List of allowed values
       * @param {{default: string}} options
       * @returns {FieldType<string>}
       */
      oneOf(allowed, {default: defaultValue}) {
        return {
          loads: (raw) => (allowed.includes(raw) ? raw : undefined),
          dumps: (value) => value,
          isDefault: (value) => value === defaultValue,
          default: defaultValue,
        };
      },

      /**
       * Array type. Order-sensitive list of values.
       *
       * Serialized as comma-separated values. Invalid items are filtered out based on `itemType.loads()` returning
       * `undefined`. Item values must not contain commas.
       *
       * Note: Empty string input (`""`) is handled specially and returns `[]` (if `allowEmpty`) or falls back to
       * `default`. It does not produce `[""]` even with `string` item type. Use `","` to get `["", ""]` with `string`.
       * `allowEmpty` is enforced on load only; dumping an empty array still serializes to `""`.
       *
       * @param {FieldType<*>} itemType - Type helper for array items
       * @param {{default: Array, allowEmpty?: boolean}} options
       *   - `allowEmpty`: If true, empty string → empty array.
       *     If false (default), empty string → falls back to `default`.
       * @returns {FieldType<Array>}
       */
      arrayOf(itemType, {default: defaultValue, allowEmpty = false}) {
        return {
          loads(raw) {
            if (raw === "") return allowEmpty ? [] : undefined;
            const valid = raw
              .split(",")
              .map((item) => itemType.loads(item))
              .filter((v) => v !== undefined);
            return valid.length > 0 ? valid : undefined;
          },
          dumps: (value) => value.map((v) => itemType.dumps(v)).join(","),
          isDefault(value) {
            return (
              value.length === defaultValue.length &&
              value.every((v, i) => v === defaultValue[i])
            );
          },
          default: defaultValue,
        };
      },

      /**
       * Set type. Order-insensitive collection of unique values.
       *
       * Like `arrayOf` but dedupes values, sorts on serialize for consistent URLs, and uses order-insensitive
       * comparison for `isDefault`. Item values must not contain commas.
       *
       * Note: Empty string input (`""`) is handled specially and returns `[]` (if `allowEmpty`) or falls back to
       * `default`. See `arrayOf` for details. `allowEmpty` is enforced on load only.
       *
       * @param {FieldType<*>} itemType - Type helper for set items
       * @param {{default: Array, allowEmpty?: boolean}} options
       *   - `allowEmpty`: If true, empty string → empty array.
       *     If false (default), empty string → falls back to `default`.
       * @returns {FieldType<Array>}
       */
      setOf(itemType, {default: defaultValue, allowEmpty = false}) {
        return {
          loads(raw) {
            if (raw === "") return allowEmpty ? [] : undefined;
            const valid = [
              ...new Set(
                raw
                  .split(",")
                  .map((item) => itemType.loads(item))
                  .filter((v) => v !== undefined)
              ),
            ];
            return valid.length > 0 ? valid : undefined;
          },
          dumps(value) {
            return [...new Set(value)]
              .map((v) => itemType.dumps(v))
              .sort()
              .join(",");
          },
          isDefault(value) {
            const a = new Set(value);
            const b = new Set(defaultValue);
            return a.size === b.size && [...a].every((v) => b.has(v));
          },
          default: defaultValue,
        };
      },
    },

    /**
     * Parse a query string into a state object according to the schema.
     *
     * For each field in the schema:
     * - If the param exists and parses successfully, use the parsed value
     * - If the param exists but parse returns undefined, use the default
     * - If the param is missing, use the default
     *
     * @param {Schema} schema
     * @param {string} queryString - Query string (with or without leading "?")
     * @returns {Object<string, unknown>}
     */
    loads(schema, queryString) {
      const params = new URLSearchParams(queryString);
      const result = {};
      for (const [key, fieldType] of Object.entries(schema)) {
        const raw = params.get(key);
        if (raw !== null) {
          const parsed = fieldType.loads(raw);
          result[key] = parsed !== undefined ? parsed : fieldType.default;
        } else {
          result[key] = fieldType.default;
        }
      }
      return result;
    },

    /**
     * Serialize a state object to a query string according to the schema.
     *
     * Default values are omitted for cleaner URLs.
     *
     * @param {Schema} schema
     * @param {Object<string, unknown>} state
     * @returns {string} Query string without leading "?"
     */
    dumps(schema, state) {
      const params = new URLSearchParams();
      for (const [key, fieldType] of Object.entries(schema)) {
        const value = state[key];
        if (value == null) continue;
        if (!fieldType.isDefault(value)) {
          params.set(key, fieldType.dumps(value));
        }
      }
      return params.toString();
    },

    /**
     * Sync state to the URL, preserving non-schema params.
     *
     * @param {Schema} schema
     * @param {Object<string, unknown>} state
     */
    // Uses replaceState (not pushState) to avoid polluting browser history with every filter change.
    // Back button navigates away entirely; state restores on return via loads.
    // Preserves non-schema params so other query params on the page aren't blown away.
    sync(schema, state) {
      const params = new URLSearchParams(location.search);
      for (const key of Object.keys(schema)) {
        params.delete(key);
      }
      for (const [key, value] of new URLSearchParams(UrlState.dumps(schema, state))) {
        params.set(key, value);
      }
      const search = params.toString();
      const url = location.pathname + (search ? `?${search}` : "") + location.hash;
      history.replaceState(null, "", url);
    },

    /**
     * Create an Alpine.js component mixin with URL-synced state.
     *
     * IMPORTANT: You must call `this.initUrlState()` in your component's `init()` method.
     *
     * @param {Schema} schema
     * @param {{key?: string}} [options]
     * @returns {Object} Alpine component mixin with state property and initUrlState method
     *
     * @example
     * const schema = {
     *   search: UrlState.types.string({ default: '' }),
     *   page: UrlState.types.number({ default: 1, min: 1 }),
     * };
     *
     * // Default key: 'urlState'
     * function myComponent() {
     *   return {
     *     ...UrlState.use(schema),
     *
     *     init() {
     *       this.initUrlState();
     *     },
     *
     *     // Access via this.urlState.search, this.urlState.page
     *   };
     * }
     *
     * // Custom key
     * function myComponent() {
     *   return {
     *     ...UrlState.use(schema, { key: 'filters' }),
     *
     *     init() {
     *       this.initUrlState();
     *     },
     *
     *     // Access via this.filters.search, this.filters.page
     *   };
     * }
     */
    use(schema, options = {}) {
      const key = options.key || "urlState";
      return {
        [key]: {},

        initUrlState() {
          this[key] = UrlState.loads(schema, location.search);
          // Deep watch catches array/set mutations like push() or index assignment.
          this.$watch(key, () => UrlState.sync(schema, this[key]), {deep: true});
        },
      };
    },
  };

  window.UrlState = UrlState;
})();
