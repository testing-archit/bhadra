import { redirect } from "next/navigation";

/** Keep old bookmarks useful after the retail demo was retired. */
export default function LegacyKhataPage() {
  redirect("/delivery");
}
