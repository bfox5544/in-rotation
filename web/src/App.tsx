import { Route, Routes } from "react-router-dom";
import { Footer } from "./components/Footer";
import { Header } from "./components/Header";
import Discover from "./pages/Discover";
import Search from "./pages/Search";
import AlbumDetail from "./pages/AlbumDetail";
import ListPage from "./pages/ListPage";
import Library from "./pages/Library";
import ForYou from "./pages/ForYou";
import Onboarding from "./pages/Onboarding";
import Account from "./pages/Account";
import ArtistPage from "./pages/Artist";
import Ask from "./pages/Ask";
import AlbumMap from "./pages/AlbumMap";
import Profile from "./pages/Profile";
import Contact from "./pages/Contact";
import DataSources from "./pages/DataSources";
import Privacy from "./pages/Privacy";
import HowItWorks from "./pages/HowItWorks";
import { useLibrary } from "./state/library";
import { useScrollMemory } from "./hooks/useScrollMemory";

export default function App() {
  const { error } = useLibrary();
  useScrollMemory();
  return (
    <>
      <Header />
      <main className="main">
        {error && <p className="notice" role="alert">{error}</p>}
        <Routes>
          <Route path="/" element={<Discover />} />
          <Route path="/search" element={<Search />} />
          <Route path="/album/:id" element={<AlbumDetail />} />
          <Route path="/library" element={<Library />} />
          <Route path="/library/listen-later" element={<ListPage />} />
          <Route path="/library/lists/:id" element={<ListPage />} />
          <Route path="/for-you" element={<ForYou />} />
          <Route path="/start" element={<Onboarding />} />
          <Route path="/account" element={<Account />} />
          <Route path="/artist/:id" element={<ArtistPage />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/map" element={<AlbumMap />} />
          <Route path="/u/:username" element={<Profile />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/data-sources" element={<DataSources />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/how-recommendations-work" element={<HowItWorks />} />
          <Route path="*" element={<section className="section"><h1 className="page-title">Page not found</h1></section>} />
        </Routes>
      </main>
      <Footer />
    </>
  );
}
