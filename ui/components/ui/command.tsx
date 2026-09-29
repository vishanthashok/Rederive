"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import { Search } from "lucide-react";
import type { ReactNode } from "react";

/** Modal command palette shell. Children are cmdk Command.Item / Command.Group nodes. */
export function CommandDialog({
  open,
  onOpenChange,
  placeholder,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  placeholder: string;
  children: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-[15vh] z-50 w-[calc(100vw-32px)] max-w-lg -translate-x-1/2 overflow-hidden rounded-xl border border-line bg-panel shadow-2xl">
          <Dialog.Title className="sr-only">Search records</Dialog.Title>
          <Dialog.Description className="sr-only">Type to filter records, then press Enter to open one.</Dialog.Description>
          <Command label="Search records" className="flex flex-col">
            <div className="flex items-center gap-2 border-b border-line px-3">
              <Search aria-hidden className="size-4 text-muted" />
              <Command.Input
                autoFocus
                placeholder={placeholder}
                className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-muted"
              />
            </div>
            <Command.List className="max-h-[50vh] overflow-y-auto p-1">
              <Command.Empty className="p-4 text-center text-sm text-muted">No matching records.</Command.Empty>
              {children}
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export const CommandItem = Command.Item;
export const CommandGroup = Command.Group;
