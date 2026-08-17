"use client";

import { useState, type FormEvent } from "react";

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
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="source-kind" className="text-subheadline font-semibold text-label">
          Kind
        </label>
        <select
          id="source-kind"
          value={kind}
          onChange={(event) => setKind(event.target.value as Kind)}
          className={`${inputClasses} bg-bg`}
        >
          {(Object.keys(KIND_LABEL) as Kind[]).map((value) => (
            <option key={value} value={value}>
              {KIND_LABEL[value]}
            </option>
          ))}
        </select>
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
            Exactly these URLs — this connector never crawls or discovers links.
          </p>
        </div>
      )}

      <p role="alert" className="text-footnote text-danger empty:hidden">
        {error ?? ""}
      </p>

      <Button rank="filled" type="submit" disabled={busy} aria-busy={busy} className="self-start">
        {busy ? "Registering…" : "Register source"}
      </Button>
    </form>
  );
}
