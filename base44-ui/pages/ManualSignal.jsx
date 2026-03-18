import React, { useState, useRef } from 'react';
import { base44 } from '@/api/base44Client';
import { Upload, ImageIcon, CheckCircle, AlertCircle, X } from 'lucide-react';

export default function ManualSignal() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [notes, setNotes] = useState('');
  const [status, setStatus] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef();

  const handleFile = (f) => { if (!f || !f.type.startsWith('image/')) return; setFile(f); setPreview(URL.createObjectURL(f)); setStatus(null); };
  const handleDrop = (e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]); };

  const handleSubmit = async () => {
    if (!file) return;
    setStatus('uploading'); setErrorMsg('');
    const { file_url } = await base44.integrations.Core.UploadFile({ file });
    setStatus('submitting');
    await base44.functions.invoke('submitManualSignal', { image_url: file_url, notes });
    setStatus('success');
    setTimeout(() => { setFile(null); setPreview(null); setNotes(''); setStatus(null); }, 3000);
  };

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-2xl mx-auto">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2"><Upload className="w-6 h-6 text-blue-400" /><h1 className="text-2xl font-bold text-slate-100 tracking-tight">Manual Signal Drop-Zone</h1></div>
        <p className="text-sm text-slate-500">Upload a TradingView screenshot for external AI processing.</p>
      </div>
      <div onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={handleDrop} onClick={() => !preview && inputRef.current?.click()} className={`card-dark rounded-xl p-8 flex flex-col items-center justify-center gap-4 transition-all duration-300 min-h-[260px] ${!preview ? 'cursor-pointer' : ''} ${dragging ? 'border-blue-500/60 bg-blue-500/5 glow-blue' : ''} ${preview ? '' : 'hover:border-slate-600 hover:bg-slate-800/30'}`}>
        <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={e => handleFile(e.target.files[0])} />
        {preview ? (<div className="relative w-full"><img src={preview} alt="Preview" className="w-full rounded-lg object-contain max-h-64" /><button onClick={e => { e.stopPropagation(); setFile(null); setPreview(null); setStatus(null); }} className="absolute top-2 right-2 p-1.5 rounded-full bg-slate-900/80 border border-slate-700 text-slate-400 hover:text-slate-200 transition-colors"><X className="w-4 h-4" /></button></div>) : (<><div className="p-4 rounded-full bg-slate-800 border border-slate-700"><ImageIcon className="w-8 h-8 text-slate-500" /></div><div className="text-center"><p className="text-sm font-semibold text-slate-300">Drop TradingView screenshot here</p><p className="text-xs text-slate-600 mt-1">or click to browse — PNG, JPG, WEBP</p></div></>)}
      </div>
      <div className="mt-4">
        <label className="text-xs font-semibold tracking-widest uppercase text-slate-500 mb-2 block">Notes (optional)</label>
        <textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Add context for the AI..." rows={3} className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 resize-none transition-all" />
      </div>
      <button onClick={handleSubmit} disabled={!file || status === 'uploading' || status === 'submitting' || status === 'success'} className={`mt-4 w-full py-3.5 rounded-xl font-semibold text-sm transition-all duration-300 ${!file || status ? 'opacity-50 cursor-not-allowed bg-slate-800 text-slate-500 border border-slate-700' : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-500/20'}`}>
        {status === 'uploading' ? 'Uploading image...' : status === 'submitting' ? 'Submitting to AI pipeline...' : status === 'success' ? '✓ Signal submitted' : 'Submit Signal for Analysis'}
      </button>
      {status === 'success' && (<div className="mt-4 flex items-center gap-2 text-emerald-400 text-sm"><CheckCircle className="w-4 h-4" /><span>Signal sent to ai_reasoning table.</span></div>)}
      {status === 'error' && (<div className="mt-4 flex items-center gap-2 text-red-400 text-sm"><AlertCircle className="w-4 h-4" /><span>{errorMsg}</span></div>)}
    </div>
  );
}