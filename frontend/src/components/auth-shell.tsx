import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Wordmark } from "@/components/brand";

/** The branded single-card layout used by the account pages people reach
 * from emails (reset password, invitation, unsubscribe). */
export function AuthShell({ title, description, children }: { title: string; description?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 px-4 py-10">
      <Link href="/login" className="rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Wordmark markClassName="size-10" />
      </Link>
      <Card className="w-full max-w-sm shadow-[0_1px_0_var(--border),0_12px_32px_-16px_oklch(0.36_0.15_279/0.35)]">
        <CardHeader>
          <CardTitle className="text-xl font-bold">{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        <CardContent className="flex flex-col gap-4 pb-6">{children}</CardContent>
      </Card>
    </div>
  );
}
