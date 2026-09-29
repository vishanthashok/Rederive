"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

const ORDER = ["system", "light", "dark"] as const;

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const current = mounted ? ((theme as (typeof ORDER)[number]) ?? "system") : "system";
  const Icon = current === "light" ? Sun : current === "dark" ? Moon : Monitor;
  const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
  return (
    <Button variant="ghost" size="icon" aria-label={`Theme: ${current}. Switch to ${next}.`} title={`Theme: ${current}`} onClick={() => setTheme(next)}>
      <Icon aria-hidden />
    </Button>
  );
}
