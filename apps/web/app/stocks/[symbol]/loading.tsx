export default function StockLoading() {
  return (
    <div className="route-loading-container">
      <div className="route-loading-bar" />
      <div className="route-loading-content">
        <div className="route-loading-spinner" />
        <p className="route-loading-text">Loading institutional stock research dossier…</p>
      </div>
    </div>
  );
}
