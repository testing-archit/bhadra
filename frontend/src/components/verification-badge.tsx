import { Badge } from "@/components/ui/badge";
import { CircleCheck, Sparkles } from "lucide-react";

export function VerificationBadge({ verifiedAt }: { verifiedAt?: string | null }) {
  return verifiedAt ? (
    <Badge variant="outline" className="gap-1 border-success/30 bg-success/10 text-foreground">
      <CircleCheck className="h-3 w-3" /> Human verified
    </Badge>
  ) : (
    <Badge variant="outline" className="gap-1 border-violet-500/20 bg-violet-500/5 text-violet-700 dark:text-violet-300">
      <Sparkles className="h-3 w-3" /> AI generated
    </Badge>
  );
}
