"use client";

import { Button } from "@/components/ui/button";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <main className="grid h-screen place-items-center p-4">
      <div className="max-w-md rounded-xl border border-line bg-panel p-6 text-center">
        <h1 className="text-base font-semibold">Something broke in the UI</h1>
        <p className="mt-2 break-words text-sm text-muted">{error.message}</p>
        <Button className="mt-4" onClick={reset}>
          Try again
        </Button>
      </div>
    </main>
  );
}
