export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer-inner">
        <span>© {new Date().getFullYear()} ProductClassifier</span>
        <span className="footer-dot">·</span>
        <span>AI-powered product categorization</span>
      </div>
    </footer>
  );
}
