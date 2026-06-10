import Link from 'next/link';
import {
  BrainCircuit,
  FileText,
  MessageSquare,
  Sparkles,
  Layers,
  Search,
  Mic,
  Shield,
  Zap,
  ArrowRight,
  ChevronRight,
} from 'lucide-react';

export default function LandingPage() {

  return (
    <div className="min-h-screen bg-[#060b14] text-white overflow-hidden">
      {/* Nav */}
      <nav className="fixed top-0 inset-x-0 z-50 border-b border-white/[0.06] bg-[#060b14]/80 backdrop-blur-xl">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 border border-primary/25">
              <BrainCircuit className="h-4 w-4 text-primary" />
            </div>
            <span className="text-[15px] font-semibold tracking-tight">MindAgent</span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="text-sm text-white/60 hover:text-white transition-colors px-3 py-1.5"
            >
              Sign in
            </Link>
            <Link
              href="/register"
              className="text-sm font-medium bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-xl transition-all hover:shadow-lg hover:shadow-primary/20"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative pt-32 pb-24 px-6">
        {/* Background glow */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-20 left-1/2 -translate-x-1/2 w-[800px] h-[600px] rounded-full bg-primary/[0.07] blur-[120px]" />
          <div className="absolute top-40 left-1/4 w-[400px] h-[400px] rounded-full bg-blue-500/[0.04] blur-[100px]" />
          <div className="absolute top-60 right-1/4 w-[300px] h-[300px] rounded-full bg-violet-500/[0.04] blur-[80px]" />
        </div>

        <div className="relative max-w-4xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-white/10 bg-white/[0.03] mb-8">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs text-white/60">Powered by RAG + AI Intelligence</span>
          </div>

          <h1 className="text-5xl sm:text-6xl lg:text-7xl font-bold tracking-tight leading-[1.1]">
            Your documents,{' '}
            <span className="gradient-text">brilliantly</span>
            <br />
            understood.
          </h1>

          <p className="mt-6 text-lg sm:text-xl text-white/50 max-w-2xl mx-auto leading-relaxed">
            Upload PDFs, ask questions in natural language, and get accurate answers
            grounded in your documents — with sources, summaries, and flashcards.
          </p>

          <div className="mt-10 flex items-center justify-center gap-4">
            <Link
              href="/register"
              className="group inline-flex items-center gap-2 bg-primary hover:bg-primary/90 text-white font-medium px-6 py-3 rounded-xl text-sm transition-all hover:shadow-xl hover:shadow-primary/25 hover:-translate-y-0.5"
            >
              Get Started Free
              <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] text-white/80 font-medium px-6 py-3 rounded-xl text-sm transition-all"
            >
              Sign in
            </Link>
          </div>
        </div>
      </section>

      {/* Feature Grid */}
      <section className="relative px-6 py-24">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
              Everything you need to master your documents
            </h2>
            <p className="mt-4 text-white/40 max-w-xl mx-auto">
              From intelligent search to AI-generated study materials — one platform.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <FeatureCard
              icon={<Search className="w-5 h-5" />}
              title="Hybrid Search"
              description="Vector similarity + keyword matching combined with RRF scoring for highly relevant retrieval."
              accent="from-blue-500/20 to-blue-600/5"
            />
            <FeatureCard
              icon={<MessageSquare className="w-5 h-5" />}
              title="Conversational Q&A"
              description="Ask follow-up questions naturally. Context-aware responses grounded in your documents."
              accent="from-violet-500/20 to-violet-600/5"
            />
            <FeatureCard
              icon={<FileText className="w-5 h-5" />}
              title="Multi-Document Reasoning"
              description="Cross-reference multiple PDFs. Compare, contrast, and find connections across your library."
              accent="from-emerald-500/20 to-emerald-600/5"
            />
            <FeatureCard
              icon={<Sparkles className="w-5 h-5" />}
              title="AI Summarization"
              description="Generate structured summaries of documents and conversations with one click."
              accent="from-amber-500/20 to-amber-600/5"
            />
            <FeatureCard
              icon={<Layers className="w-5 h-5" />}
              title="Flashcard Generation"
              description="Auto-generate study flashcards from any document or conversation for active recall."
              accent="from-rose-500/20 to-rose-600/5"
            />
            <FeatureCard
              icon={<Mic className="w-5 h-5" />}
              title="Voice Answers"
              description="Listen to AI responses with natural text-to-speech — perfect for hands-free learning."
              accent="from-cyan-500/20 to-cyan-600/5"
            />
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="relative px-6 py-24 border-t border-white/[0.04]">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
              Simple. Fast. Intelligent.
            </h2>
            <p className="mt-4 text-white/40 max-w-xl mx-auto">
              Get answers from your documents in three steps.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <StepCard
              number="01"
              title="Upload"
              description="Drop your PDFs — they're automatically chunked, embedded, and indexed for search."
            />
            <StepCard
              number="02"
              title="Ask"
              description="Type a question naturally. Our hybrid retrieval finds the most relevant passages."
            />
            <StepCard
              number="03"
              title="Understand"
              description="Get accurate answers with source citations, or generate summaries and flashcards."
            />
          </div>
        </div>
      </section>

      {/* Trust bar */}
      <section className="relative px-6 py-16 border-t border-white/[0.04]">
        <div className="max-w-4xl mx-auto">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            <TrustItem
              icon={<Shield className="w-4 h-4" />}
              title="Secure by default"
              description="Row-level security ensures your documents stay private. Only you can access your data."
            />
            <TrustItem
              icon={<Zap className="w-4 h-4" />}
              title="Serverless & fast"
              description="Built on AWS Lambda — scales to zero, responds in seconds, no cold-start delays."
            />
            <TrustItem
              icon={<BrainCircuit className="w-4 h-4" />}
              title="Multiple AI models"
              description="Powered by Sarvam, Voyage AI, and NVIDIA NIM — the best model for each task."
            />
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="relative px-6 py-24 border-t border-white/[0.04]">
        <div className="relative max-w-3xl mx-auto text-center">
          <div className="absolute inset-0 -m-12 rounded-3xl bg-gradient-to-b from-primary/[0.06] to-transparent pointer-events-none" />
          <div className="relative">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
              Ready to understand your documents?
            </h2>
            <p className="mt-4 text-white/40">
              Join MindAgent and turn static PDFs into interactive knowledge.
            </p>
            <Link
              href="/register"
              className="group mt-8 inline-flex items-center gap-2 bg-primary hover:bg-primary/90 text-white font-medium px-8 py-3.5 rounded-xl text-sm transition-all hover:shadow-xl hover:shadow-primary/25 hover:-translate-y-0.5"
            >
              Get Started Free
              <ChevronRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/[0.04] px-6 py-8">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-4 w-4 text-white/30" />
            <span className="text-sm text-white/30">MindAgent</span>
          </div>
          <p className="text-xs text-white/20">
            Built with RAG, serverless, and a lot of curiosity.
          </p>
        </div>
      </footer>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  description,
  accent,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  accent: string;
}) {
  return (
    <div className="group relative rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 transition-all hover:border-white/[0.12] hover:bg-white/[0.04]">
      <div className={`absolute inset-0 rounded-2xl bg-gradient-to-br ${accent} opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none`} />
      <div className="relative">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-white/70 group-hover:text-white group-hover:border-white/20 transition-colors">
          {icon}
        </div>
        <h3 className="mt-4 text-[15px] font-semibold text-white">{title}</h3>
        <p className="mt-2 text-sm text-white/40 leading-relaxed">{description}</p>
      </div>
    </div>
  );
}

function StepCard({
  number,
  title,
  description,
}: {
  number: string;
  title: string;
  description: string;
}) {
  return (
    <div className="text-center">
      <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl border border-primary/20 bg-primary/[0.06] mb-4">
        <span className="text-sm font-bold text-primary">{number}</span>
      </div>
      <h3 className="text-lg font-semibold text-white">{title}</h3>
      <p className="mt-2 text-sm text-white/40 leading-relaxed">{description}</p>
    </div>
  );
}

function TrustItem({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center text-center px-4">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.04] border border-white/[0.08] text-white/50 mb-3">
        {icon}
      </div>
      <h4 className="text-sm font-semibold text-white/80">{title}</h4>
      <p className="mt-1.5 text-xs text-white/35 leading-relaxed">{description}</p>
    </div>
  );
}
