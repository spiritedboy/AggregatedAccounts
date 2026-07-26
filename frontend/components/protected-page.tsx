import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";

export function ProtectedPage({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
