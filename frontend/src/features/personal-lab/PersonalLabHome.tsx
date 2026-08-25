import { BookOpenText, MessageSquareText, Settings2 } from "lucide-react"
import { Link } from "react-router-dom"

import { useLocaleContext } from "../../app/locale-provider"
import "./personal-lab.css"

const personalSteps = [
  { icon: BookOpenText, key: "personal_home_knowledge", to: "/app/knowledge" },
  { icon: Settings2, key: "personal_home_settings", to: "/app/settings" },
  { icon: MessageSquareText, key: "personal_home_chat", to: "/app/chat" },
] as const

export function PersonalLabHome(): React.JSX.Element {
  const { t } = useLocaleContext()

  return (
    <section aria-labelledby="personal-path-title" className="rs-personal-home">
      <p className="rs-personal-home__scope">{t("personal_home_scope")}</p>
      <h2 id="personal-path-title">{t("personal_home_path_title")}</h2>
      <ol className="rs-personal-home__path">
        {personalSteps.map(({ icon: Icon, key, to }) => (
          <li key={to}>
            <Link className="rs-personal-home__step" to={to}>
              <Icon aria-hidden="true" size={20} />
              <span>{t(key)}</span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  )
}
