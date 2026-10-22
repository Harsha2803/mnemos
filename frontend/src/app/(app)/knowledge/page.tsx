"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { DocumentList } from "@/components/knowledge/DocumentList";
import { UploadControl } from "@/components/knowledge/UploadControl";
import { PageHeader, SectionHeading } from "@/components/ui/PageHeader";
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
      <PageHeader
        title="Knowledge"
        description="The documents Mnemos answers from. Upload them here or ingest them from a source; superseded revisions stay on record and are never quoted."
      />

      <UploadControl
        onUploaded={() => void queryClient.invalidateQueries({ queryKey: KNOWLEDGE_QUERY_KEY })}
      />

      <section className="flex flex-col gap-3" aria-labelledby="documents-heading">
        <SectionHeading id="documents-heading">Documents</SectionHeading>
        {isPending ? (
          <div className="flex flex-col gap-2" role="status" aria-label="Loading documents">
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
