import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { Filters } from "../types";

export type Preset = "7d" | "30d" | "90d" | "180d" | "365d" | "all";

const PRESET_DAYS: Record<Preset, number> = { "7d": 7, "30d": 30, "90d": 90, "180d": 180, "365d": 365, all: 3650 };

export const CATEGORIES = [
  "All",
  "Electronics",
  "Home & Kitchen",
  "Fashion",
  "Beauty",
  "Sports & Outdoors",
  "Books",
  "Toys & Games",
  "Grocery",
];

export const REGIONS = ["All", "North America", "Europe", "Asia Pacific", "Latin America", "Middle East & Africa"];

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export function rangeForPreset(preset: Preset): { start_date: string; end_date: string } {
  return { start_date: isoDaysAgo(PRESET_DAYS[preset]), end_date: new Date().toISOString().slice(0, 10) };
}

interface FiltersContextValue {
  filters: Filters;
  preset: Preset;
  setPreset: (preset: Preset) => void;
  setCategory: (category: string) => void;
  setRegion: (region: string) => void;
  query: Record<string, string>;
  reset: () => void;
  refreshToken: number;
  refresh: () => void;
}

const FiltersContext = createContext<FiltersContextValue | null>(null);

export function FiltersProvider({ children }: { children: React.ReactNode }) {
  const [preset, setPresetState] = useState<Preset>("90d");
  const [category, setCategoryState] = useState("All");
  const [region, setRegionState] = useState("All");
  const [refreshToken, setRefreshToken] = useState(0);

  const filters = useMemo<Filters>(() => {
    const range = rangeForPreset(preset);
    return { ...range, category, region };
  }, [preset, category, region]);

  const query = useMemo<Record<string, string>>(() => {
    const q: Record<string, string> = { start_date: filters.start_date, end_date: filters.end_date };
    if (category !== "All") q.category = category;
    if (region !== "All") q.region = region;
    return q;
  }, [filters, category, region]);

  const refresh = useCallback(() => setRefreshToken((t) => t + 1), []);

  const value: FiltersContextValue = {
    filters,
    preset,
    setPreset: setPresetState,
    setCategory: setCategoryState,
    setRegion: setRegionState,
    query,
    reset: () => {
      setPresetState("90d");
      setCategoryState("All");
      setRegionState("All");
    },
    refreshToken,
    refresh,
  };

  return <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>;
}

export function useFilters(): FiltersContextValue {
  const ctx = useContext(FiltersContext);
  if (!ctx) throw new Error("useFilters must be used inside FiltersProvider");
  return ctx;
}
