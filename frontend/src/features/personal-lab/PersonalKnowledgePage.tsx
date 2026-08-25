import { BookOpenText } from "lucide-react"

import { useLocaleContext } from "../../app/locale-provider"
import { IngestionPanel } from "../ingestion/IngestionPanel"
import "./personal-lab.css"

export function PersonalKnowledgePage(): React.JSX.Element {
  const { t } = useLocaleContext()

  return (
    <section
      aria-label={t("personal_knowledge_region")}
      className="rs-personal-knowledge rs-personal-knowledge--with-ingestion"
    >
      <div className="rs-personal-knowledge__intro">
        <BookOpenText aria-hidden="true" size={24} />
        <p>{t("personal_knowledge_handoff")}</p>
      </div>
      <IngestionPanel refreshToken={0} />
    </section>
  )
}
