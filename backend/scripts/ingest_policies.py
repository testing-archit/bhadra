import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.company_policies import POLICY_CHUNKS
from app.services import qdrant_service


def main() -> None:
    qdrant_service.upsert_policy_chunks(POLICY_CHUNKS)
    print(f"Upserted {len(POLICY_CHUNKS)} policy chunks into collection "
          f"'{qdrant_service.POLICY_COLLECTION}'.")


if __name__ == "__main__":
    main()
