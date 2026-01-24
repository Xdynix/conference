(function () {
  const CONFERENCE_CACHE_PREFIX = "conference.";

  function createCachedStore(key, initialState, fetcher, {afterLoad} = {}) {
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
          this.update(data);
          if (afterLoad) afterLoad.call(this);
        } finally {
          this.loading = false;
        }
      },

      // Replace store state with new data and persist to cache.
      update(data) {
        for (const key of Object.keys(this)) {
          if (key !== "loading" && typeof this[key] !== "function" && !(key in data)) {
            delete this[key];
          }
        }
        Object.assign(this, data);
        this.save();
      },

      // Persist current store state to cache. Call after modifying individual properties.
      save() {
        const data = {};
        for (const [key, value] of Object.entries(this)) {
          if (key !== "loading" && typeof value !== "function") {
            data[key] = value;
          }
        }
        localStorage.setItem(cacheKey, JSON.stringify(data));
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
          const {data} = await api.get(APP.urls.conference.list, {
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
        },
        {
          afterLoad() {
            const validNames = new Set(this.items.map((c) => c.name));
            const prefix = `cache.${CONFERENCE_CACHE_PREFIX}`;
            for (const key of Object.keys(localStorage)) {
              if (!key.startsWith(prefix)) continue;
              const name = key.slice(prefix.length);
              if (name !== "_" && !validNames.has(name)) {
                localStorage.removeItem(key);
              }
            }
          },
        }
      ),
    );

    const conferenceName = APP.params?.conference_name;
    Alpine.store("conference", createCachedStore(
      `${CONFERENCE_CACHE_PREFIX}${conferenceName || "_"}`,
      {detail: null, profile: null},
      async () => {
        if (!conferenceName) return {detail: null, profile: null};

        const result = {detail: null, profile: null};

        const [detailResult, profileResult] = await Promise.allSettled([
          api.get(APP.urls.conference.get(conferenceName)),
          api.get(APP.urls.conference.getProfile(conferenceName)),
        ]);

        if (detailResult.status === "fulfilled") {
          result.detail = detailResult.value.data;
        }
        if (profileResult.status === "fulfilled") {
          result.profile = profileResult.value.data;
        }

        return result;
      }
    ));

    Alpine.store("permissions", {
      canReview: false,
      hasAdminRole: false,
      isConferenceAdmin: false,
      isChairRole: false,
    });

    Alpine.effect(() => {
      const name = Alpine.store("conference")?.detail?.name;
      if (name && document.title.endsWith(APP.config.siteName)) {
        document.title = document.title.replace(APP.config.siteName, name);
      }
    });

    Alpine.effect(() => {
      const enums = APP.enums;
      const user = Alpine.store("session")?.user;
      const profile = Alpine.store("conference")?.profile;
      const permissions = Alpine.store("permissions");

      const isSuperuserOrGlobalAdmin =
        user?.is_superuser || user?.roles?.includes(enums.GlobalRole.ADMIN.value);

      const hasConferenceRole = (roles) =>
        profile?.conference_roles?.some((r) => roles.includes(r));

      const hasTrackRole = (roles) =>
        profile?.track_roles?.some((tr) => roles.includes(tr.role));

      permissions.canReview = isSuperuserOrGlobalAdmin
        || hasConferenceRole(enums.ConferenceRole._collections.reviewers)
        || hasTrackRole(enums.TrackRole._collections.reviewers);

      permissions.hasAdminRole = isSuperuserOrGlobalAdmin
        || hasConferenceRole(enums.ConferenceRole._collections.admins)
        || hasTrackRole(enums.TrackRole._collections.admins);

      permissions.isConferenceAdmin = isSuperuserOrGlobalAdmin
        || hasConferenceRole(enums.ConferenceRole._collections.admins);

      permissions.isChairRole = isSuperuserOrGlobalAdmin
        || hasConferenceRole([enums.ConferenceRole.CHAIR.value]);
    });

    Alpine.store("sidebar", {
      active: null,
      setActive(key) {
        this.active = key;
      },
    });

    Alpine.store("breadcrumb", {
      items: [],
      set(items) {
        this.items = items;
      },
    });
  });
})();
