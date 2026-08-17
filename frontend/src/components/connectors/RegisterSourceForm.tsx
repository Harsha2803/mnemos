"use client";

import { Database, FolderOpen, Globe, type LucideIcon } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { registerSource, type RegisterSourceRequest } from "@/lib/connectors/api";

export type RegisterSourceFormProps = {
  onRegistered: () => void;
};

type Kind = RegisterSourceRequest["kind"];

const KIND_LABEL: Record<Kind, string> = {
  s3: "S3 bucket",
  minio: "MinIO bucket",
  local_fs: "Local filesystem directory",
  http: "Curated list of URLs",
};

const KIND_ICON: Record<Kind, LucideIcon> = { s3: Database, minio: Database, local_fs: FolderOpen, http: Globe };

const inputClasses =
  "hit-target rounded-md border border-separator bg-bg px-4 text-body text-label placeholder:text-label-tertiary focus-visible:border-accent";

/**
 * One form, three shapes: which fields it shows depends on `kind`, matching
 * `entrypoints/cli.py`'s `_connector_config` — the same three connector
 * kinds accept the same three configs, browser and terminal alike.
 */
export function RegisterSourceForm({ onRegistered }: RegisterSourceFormProps) {
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("local_fs");
  const [bucket, setBucket] = useState("");
  const [prefix, setPrefix] = useState("");
  const [root, setRoot] = useState("");
  const [urls, setUrls] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const slugPreview = slugify(slug);
  const urlLines = useMemo(() => urls.split("\n").map((line) => line.trim()).filter(Boolean), [urls]);
  const invalidUrls = useMemo(() => urlLines.filter((line) => !isHttpUrl(line)), [urlLines]);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: RegisterSourceRequest = { slug: slug.trim(), name: name.trim(), kind };
      if (kind === "s3" || kind === "minio") {
        body.bucket = bucket.trim();
        body.prefix = prefix.trim();
      } else if (kind === "local_fs") {
        body.root = root.trim();
      } else {
        body.urls = urls
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line.length > 0);
      }
      await registerSource(body);
      setSlug("");
      setName("");
      setBucket("");
      setPrefix("");
      setRoot("");
      setUrls("");
      onRegistered();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "could not register this source");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(event) => void onSubmit(event)}
      className="flex flex-col gap-4 rounded-lg border border-separator bg-bg-secondary p-6"
      noValidate
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <label htmlFor="source-name" className="text-subheadline font-semibold text-label">
            Name
          </label>
          <input
            id="source-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            placeholder="Handbook fileshare"
            className={inputClasses}
          />
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor="source-slug" className="text-subheadline font-semibold text-label">
            Slug
          </label>
          <input
            id="source-slug"
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            required
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            placeholder="handbook-fileshare"
            className={inputClasses}
          />
          <p className="text-footnote text-label-secondary">
            URL preview: <code className="font-mono">/sources/{slugPreview || "source-slug"}</code>
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-subheadline font-semibold text-label">Provider</span>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="radiogroup" aria-label="Source provider">
          {(Object.keys(KIND_LABEL) as Kind[]).map((value) => {
            const Icon = KIND_ICON[value];
            return (
              <button key={value} type="button" role="radio" aria-checked={kind === value} onClick={() => setKind(value)} className="hit-target flex flex-col items-start rounded-md border border-separator p-3 text-left text-footnote text-label-secondary hover:bg-fill-tertiary aria-checked:border-accent aria-checked:bg-accent-tint aria-checked:text-accent">
                <Icon className="mb-2 size-5" strokeWidth={1.5} aria-hidden="true" />
                <span className="font-semibold">{KIND_LABEL[value]}</span>
              </button>
            );
          })}
        </div>
      </div>

      {(kind === "s3" || kind === "minio") && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <label htmlFor="source-bucket" className="text-subheadline font-semibold text-label">
              Bucket
            </label>
            <input
              id="source-bucket"
              value={bucket}
              onChange={(event) => setBucket(event.target.value)}
              required
              placeholder="mnemos-documents"
              className={inputClasses}
            />
          </div>
          <div className="flex flex-col gap-2">
            <label htmlFor="source-prefix" className="text-subheadline font-semibold text-label">
              Prefix (optional)
            </label>
            <input
              id="source-prefix"
              value={prefix}
              onChange={(event) => setPrefix(event.target.value)}
              placeholder="handbooks/"
              className={inputClasses}
            />
          </div>
        </div>
      )}

      {kind === "local_fs" && (
        <div className="flex flex-col gap-2">
          <label htmlFor="source-root" className="text-subheadline font-semibold text-label">
            Root directory
          </label>
          <input
            id="source-root"
            value={root}
            onChange={(event) => setRoot(event.target.value)}
            required
            placeholder="/fixtures/sources"
            className={inputClasses}
          />
          <p className="text-footnote text-label-secondary">
            Must be inside a directory the deployment operator has approved
            (<code className="font-mono">MNEMOS_LOCAL_FS_ALLOWED_ROOTS</code>).
          </p>
        </div>
      )}

      {kind === "http" && (
        <div className="flex flex-col gap-2">
          <label htmlFor="source-urls" className="text-subheadline font-semibold text-label">
            URLs, one per line
          </label>
          <textarea
            id="source-urls"
            value={urls}
            onChange={(event) => setUrls(event.target.value)}
            required
            rows={4}
            placeholder={"https://example.com/handbook.pdf"}
            className={`${inputClasses} py-3`}
          />
          <p className="text-footnote text-label-secondary">
            {urlLines.length} URL{urlLines.length === 1 ? "" : "s"}. Exactly these URLs — this connector never crawls or discovers links.
          </p>
          {invalidUrls.length > 0 && <p className="text-footnote text-danger">{invalidUrls.length} line{invalidUrls.length === 1 ? " is" : "s are"} not a valid HTTP(S) URL.</p>}
        </div>
      )}

      <p role="alert" className="text-footnote text-danger empty:hidden">
        {error ?? ""}
      </p>

      <Button rank="filled" type="submit" disabled={busy || (kind === "http" && invalidUrls.length > 0)} aria-busy={busy} className="self-start">
        {busy ? "Registering…" : "Register source"}
      </Button>
    </form>
  );
}

function slugify(value: string): string {
  return value.trim().toLocaleLowerCase().replaceAll(/[^a-z0-9]+/g, "-").replaceAll(/^-|-$/g, "");
}

function isHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}
