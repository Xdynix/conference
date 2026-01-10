function createCachedStore(key, initialState, fetcher) {
  const cacheKey = `cache.${key}`;
  const cached = localStorage.getItem(cacheKey);

  return {
    ...initialState,
    ...(cached ? JSON.parse(cached) : {}),

    init() {
      this.load().catch((err) => {
        console.warn(`Failed to load store "${key}":`, err);
      });
    },

    async load() {
      const data = await fetcher();
      Object.assign(this, data);
      localStorage.setItem(cacheKey, JSON.stringify(data));
    },

    clear() {
      Object.assign(this, initialState);
      localStorage.removeItem(cacheKey);
    }
  };
}

document.addEventListener("alpine:init", () => {
  Alpine.store(
    "session",
    createCachedStore("session", {}, async () => {
      const {data} = await api.get(APP.urls.session.get);
      return data;
    }),
  );
});
