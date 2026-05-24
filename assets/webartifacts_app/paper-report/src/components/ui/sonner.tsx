import { useTheme } from "next-themes"
import { Toaster as Sonner } from "sonner"

type ToasterProps = React.ComponentProps<typeof Sonner>

const Toaster = ({ className, ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme()

  // Merge caller's className with the hard-coded "toaster group" — sonner's
  // internal toastOptions uses `group-[.toaster]:...` Tailwind variants that
  // depend on the wrapper carrying the `toaster` class. Spreading {...props}
  // AFTER `className=` would have let a caller-supplied className silently
  // wipe these two classes; merging here preserves both. (delta change 2
  // needed `rd-toaster` here so the @media print block can hide the toast
  // container on paper.)
  const mergedClassName = ["toaster group", className].filter(Boolean).join(" ")

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className={mergedClassName}
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
