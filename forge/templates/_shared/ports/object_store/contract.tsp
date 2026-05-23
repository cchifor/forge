// object_store_port — TypeSpec contract for the blob-I/O port.
//
// Source of truth: RFC-005 § "Port Contracts" → object_store_port.
// The `interface ObjectStore` block matches the RFC verbatim. Supporting
// `model` declarations (ObjectData) are introduced here because the RFC
// referenced the type without defining it; the shape mirrors the Python
// reference at
// `forge/features/object_store/templates/object_store_port/python/files/src/app/ports/object_store.py`
// (a `bytes` body plus optional metadata + content-type).
//
// Spec-only. No code is generated from this file today.
//
// Reconciliation notes:
//   * Python `stream(bucket, key) -> AsyncIterator[bytes]` is intentionally
//     OUT of this contract — the RFC defines the 80% blob shape and leaves
//     chunked streaming to language-specific extensions. Adapters MAY
//     expose `stream` as an additional method.
//   * Python `presigned_url(method=...)` is split here into `presignGet` /
//     `presignPut`, matching the RFC's enumeration. Adapters that share
//     one impl behind a `method` switch MAY do so; the cross-language
//     contract is the two-method form.

import "@typespec/openapi3";

@service(#{ title: "Object Store Port" })
namespace ForgeObjectStore;

@doc("Bytes + metadata returned by `get`.")
model ObjectData {
  @doc("Object payload.")
  body: bytes;
  @doc("MIME type as recorded on `put`; empty if the adapter does not track it.")
  contentType?: string;
  @doc("User-supplied metadata key/value pairs.")
  metadata?: Record<string>;
}

@doc("Cross-language object-store capability — put / get / delete + presigned URLs.")
interface ObjectStore {
  @doc("Upload `body` to `bucket/key`. Overwrites any existing object at that path.")
  put(bucket: string, key: string, body: bytes, metadata?: Record<string>): void;

  @doc("Download the object at `bucket/key`.")
  get(bucket: string, key: string): ObjectData;

  @doc("Remove the object at `bucket/key`. Idempotent — deleting a missing object is not an error.")
  delete(bucket: string, key: string): void;

  @doc("Return a time-limited URL the client can GET to download the object.")
  presignGet(bucket: string, key: string, ttlSeconds: int32): string;

  @doc("Return a time-limited URL the client can PUT to upload the object.")
  presignPut(bucket: string, key: string, ttlSeconds: int32): string;
}
