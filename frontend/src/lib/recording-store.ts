export interface StoredRecordingChunk {
  key: string;
  recordingId: string;
  index: number;
  blob: Blob;
  createdAt: number;
}

const DATABASE_NAME = "charcha-recordings";
const STORE_NAME = "chunks";

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, 1);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        const store = database.createObjectStore(STORE_NAME, { keyPath: "key" });
        store.createIndex("recordingId", "recordingId", { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function saveRecordingChunk(
  recordingId: string,
  index: number,
  blob: Blob
): Promise<void> {
  const database = await openDatabase();
  const transaction = database.transaction(STORE_NAME, "readwrite");
  transaction.objectStore(STORE_NAME).put({
    key: `${recordingId}:${index}`,
    recordingId,
    index,
    blob,
    createdAt: Date.now(),
  } satisfies StoredRecordingChunk);
  await new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
  database.close();
}

export async function listRecordingChunks(recordingId: string): Promise<StoredRecordingChunk[]> {
  const database = await openDatabase();
  const transaction = database.transaction(STORE_NAME, "readonly");
  const index = transaction.objectStore(STORE_NAME).index("recordingId");
  const chunks = await requestResult(index.getAll(IDBKeyRange.only(recordingId)));
  database.close();
  return (chunks as StoredRecordingChunk[]).sort((a, b) => a.index - b.index);
}

export async function deleteRecordingChunk(recordingId: string, index: number): Promise<void> {
  const database = await openDatabase();
  const transaction = database.transaction(STORE_NAME, "readwrite");
  transaction.objectStore(STORE_NAME).delete(`${recordingId}:${index}`);
  await new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
  database.close();
}
