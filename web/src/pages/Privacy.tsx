import { Link } from "react-router-dom";
import { InfoPage, InfoSection } from "../components/InfoPage";

/** What the site keeps, who else sees it and for how long (2026-11-10, before going public without a password).
 *  Short and plain, no first person (owner requests). Keep it true to the code: backend/app/schema.py,
 *  app/limits.py, app/cleanup.py, deploy/jobs.sh, chat/. */
export default function Privacy() {
  return (
    <InfoPage title="Privacy" lead="In Rotation is here to help you find albums, not to collect data about you.">
      <InfoSection title="What's Kept">
        <p>
          Your ratings, lists and Ask chats, linked to a random code in your browser. If you make an account, also your
          email, name, username and any profile picture. Passwords are scrambled so nobody can read them. Profiles are
          private unless you make them public.
        </p>
      </InfoSection>

      <InfoSection title="What Isn't">
        <p>
          No ads, analytics, tracking or cookies. Your network address isn't stored.
        </p>
      </InfoSection>

      <InfoSection title="Who Else Sees It">
        <p>
          Cloudflare and OVHcloud run the network and server the site is on. If you use Ask, your messages go to Google's
          Gemini to write replies, and Google doesn't use them to improve its products. Nothing about you is sold or
          shared with anyone else.
        </p>
      </InfoSection>

      <InfoSection title="Deleting Your Data">
        <p>
          You can delete your account at any time under Settings on your profile, and everything in it goes with it.
          Libraries without an account are cleared out after a while unused. For anything else, send a note through
          the <Link to="/contact">Contact</Link> page.
        </p>
      </InfoSection>
    </InfoPage>
  );
}
