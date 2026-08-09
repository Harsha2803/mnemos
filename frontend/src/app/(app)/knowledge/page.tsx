"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { DocumentList } from "@/components/knowledge/DocumentList";
import { UploadControl } from "@/components/knowledge/UploadControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { deleteDocument, fetchDocuments, KNOWLEDGE_QUERY_KEY } from "@/lib/knowledge/api";

export default function KnowledgePage() {
  const queryClient = useQueryClient();
  const { data, isPending } = useQuery({
    queryKey: KNOWLEDGE_QUERY_KEY,
    queryFn: ({ signal }) => fetchDocuments(signal),
  });

  const remove = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY }),
  });

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-large-title font-semibold tracking-title text-label">Knowledge</h1>
        <p className="text-callout leading-relaxed text-label-secondary">
          Upload a document, then ask about it in a chat with{" "}
          <span className="font-semibold">Use documents</span> turned on. Answers cite the
          passages they drew from, and the citation opens the source.
        </p>
      </header>

      <UploadControl
        onUploaded={() => void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY })}
      />

      <section className="flex flex-col gap-3" aria-labelledby="documents-heading">
        <h2 id="documents-heading" className="text-title-3 font-semibold tracking-title">
          Documents
        </h2>
        {isPending ? (
          <div className="flex flex-col gap-2" aria-hidden="true">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : (
          <DocumentList
            documents={data ?? []}
            onDelete={async (documentId) => {
              await remove.mutateAsync(documentId);
            }}
          />
        )}
      </section>
    </div>
  );
}
