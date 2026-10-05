import { useRef } from "react";
import { FilePlus2, Trash2, XCircle } from "lucide-react";

export default function FileDropzone({
  files,
  onChange,
}: {
  files: File[];
  onChange: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const incoming = Array.from(list);
    const allowed = incoming.filter((f) =>
      /\.(pdf|png|jpe?g|tiff?|webp)$/i.test(f.name)
    );
    onChange([...files, ...allowed]);
  };

  const remove = (index: number) => {
    onChange(files.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-4">
      <div
        className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 px-6 py-8 text-center transition hover:border-blue-400 hover:bg-blue-50/50"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          addFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
      >
        <FilePlus2 className="h-8 w-8 text-slate-400" />
        <p className="text-sm font-medium text-slate-700">
          Kéo thả chứng từ vào đây, hoặc{" "}
          <span className="text-blue-600 underline">chọn file</span>
        </p>
        <p className="text-xs text-slate-500">PDF, PNG, JPG, TIFF, WEBP — nhiều file cùng lúc</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp"
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`} className="flex items-center justify-between px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-800">{file.name}</p>
                <p className="text-xs text-slate-500">{(file.size / 1024).toFixed(1)} KB</p>
              </div>
              <button
                type="button"
                onClick={() => remove(index)}
                className="rounded-md p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                aria-label="remove file"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {files.length === 0 && (
        <p className="text-center text-xs text-slate-400">
          <XCircle className="mr-1 inline h-3.5 w-3.5" /> Chưa có file nào được thêm
        </p>
      )}
    </div>
  );
}
