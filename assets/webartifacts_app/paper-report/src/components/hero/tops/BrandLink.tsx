// The tool's name on the report's first screen, linking to the repository.
// Shown wherever a top used to print the raw skill version
// ("paper-search-pro/2.5.0"): "Paper Search Pro 2.5" reads as a signature,
// not an ad, and a forwarded report lets its reader find the tool.

export const REPO_URL = "https://github.com/O0000-code/paper-search-pro"

/** "paper-search-pro/2.5.0" -> "Paper Search Pro 2.5"; no version -> "Paper Search Pro". */
export function brandLabel(skillVersion?: string): string {
  const version = (skillVersion || "").split("/")[1] || ""
  const majorMinor = version.split(".").slice(0, 2).join(".")
  return majorMinor ? `Paper Search Pro ${majorMinor}` : "Paper Search Pro"
}

export function BrandLink({ skillVersion }: { skillVersion?: string }) {
  return (
    <a
      className="psp-brand-link"
      href={REPO_URL}
      target="_blank"
      rel="noopener noreferrer"
    >
      {brandLabel(skillVersion)}
    </a>
  )
}
