function createCachedStore(key, initialState, fetcher) {
  const cacheKey = `cache.${key}`;
  let cachedValue = null;
  try {
    const cached = localStorage.getItem(cacheKey);
    if (cached) cachedValue = JSON.parse(cached);
  } catch {
    cachedValue = null;
  }

  return {
    ...initialState,
    ...(cachedValue || {}),
    loading: !cachedValue,

    init() {
      this.load().catch((err) => {
        console.warn(`Failed to load store "${key}":`, err);
      });
    },

    async load() {
      try {
        const data = await fetcher();
        Object.assign(this, data);
        localStorage.setItem(cacheKey, JSON.stringify(data));
      } finally {
        this.loading = false;
      }
    },

    clear() {
      Object.assign(this, initialState);
      localStorage.removeItem(cacheKey);
    }
  };
}

document.addEventListener("alpine:init", () => {
  Alpine.store("session", {
    ...createCachedStore("session", {}, async () => {
      const {data} = await api.get(APP.urls.session.get);
      return data;
    }),

    async logout() {
      await api.delete(APP.urls.session.delete);
      this.clear();
      window.location.reload();
    },
  });

  Alpine.store("conferences", createCachedStore(
    "conferences",
    {items: []},
    async () => {
      const {data} = await api.get(APP.urls.conferences.list, {
        params: {page_size: 100}
      });
      const items = [...data.items].sort((a, b) => {
        const aDate = a.start_date || a.end_date;
        const bDate = b.start_date || b.end_date;
        if (aDate && bDate) return aDate.localeCompare(bDate) || a.name.localeCompare(b.name);
        if (aDate) return -1;
        if (bDate) return 1;
        return a.name.localeCompare(b.name);
      });
      return {items};
    }
  ));
});
