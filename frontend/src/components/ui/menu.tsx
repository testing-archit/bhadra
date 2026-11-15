"use client";

import * as React from "react";
import { Menu as MenuPrimitive } from "@base-ui/react/menu";
import { cn } from "@/lib/utils";

const Menu = MenuPrimitive.Root;
const MenuTrigger = MenuPrimitive.Trigger;
const MenuGroup = MenuPrimitive.Group;

function MenuContent({
  className,
  align = "start",
  side = "bottom",
  sideOffset = 6,
  children,
  ...props
}: MenuPrimitive.Popup.Props & {
  align?: MenuPrimitive.Positioner.Props["align"];
  side?: MenuPrimitive.Positioner.Props["side"];
  sideOffset?: number;
}) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Positioner align={align} side={side} sideOffset={sideOffset} className="z-50 outline-none">
        <MenuPrimitive.Popup
          className={cn(
            "min-w-52 origin-(--transform-origin) rounded-xl border bg-popover p-1 text-sm text-popover-foreground shadow-lg outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0",
            className,
          )}
          {...props}
        >
          {children}
        </MenuPrimitive.Popup>
      </MenuPrimitive.Positioner>
    </MenuPrimitive.Portal>
  );
}

function MenuItem({ className, ...props }: MenuPrimitive.Item.Props) {
  return (
    <MenuPrimitive.Item
      className={cn(
        "flex cursor-default items-center gap-2.5 rounded-lg px-2.5 py-2 outline-none select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground data-disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

function MenuLabel({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("px-2.5 pt-2 pb-1 text-xs font-medium text-muted-foreground", className)} {...props} />;
}

function MenuSeparator({ className }: { className?: string }) {
  return <MenuPrimitive.Separator className={cn("my-1 h-px bg-border", className)} />;
}

export { Menu, MenuGroup, MenuTrigger, MenuContent, MenuItem, MenuLabel, MenuSeparator };
