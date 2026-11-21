import { useEffect, useRef, useState } from 'react';

// A small grey "Copyright Notice" link at the foot of the Reports page.
// Choosing it opens a text popup laid over the page, in the same spirit as
// the gallery's overlay/lightbox: Esc, the Close button or a click on the
// backdrop all dismiss it. The panel scrolls on its own so the long notice
// never pushes the page. Focus moves to Close on open and body scrolling is
// locked while it is up, matching PhotoLightbox.
export default function CopyrightNotice() {
  const [open, setOpen] = useState(false);
  const closeRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open]);

  return (
    <>
      <p className="notice-link-wrap">
        <button type="button" className="notice-link" onClick={() => setOpen(true)}>
          Copyright Notice
        </button>
      </p>

      {open && (
        <div
          className="notice-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="copyright-title"
          onClick={() => setOpen(false)}
        >
          <div className="notice-modal__panel" onClick={(e) => e.stopPropagation()}>
            <div className="notice-modal__head">
              <h2 id="copyright-title">Copyright</h2>
              <button
                ref={closeRef}
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setOpen(false)}
              >
                Close
              </button>
            </div>

            <div className="notice-modal__body">
              <p className="lead">Copyright and reuse</p>
              <p>
                © 2026 colnrg.app. All rights reserved, except as expressly permitted
                below or by applicable law.
              </p>

              <h3>1. Copyright ownership</h3>
              <p>
                Unless otherwise indicated, the original text, graphics, figures and
                other original material in this report are protected by copyright and
                are owned by, or licensed to, the owner.
              </p>
              <p>
                This notice does not claim ownership of facts, ideas or methods as such,
                or of third-party material identified in the report. Any third-party
                material remains subject to its own applicable copyright and licensing
                terms.
              </p>

              <h3>2. Permitted non-commercial use</h3>
              <p>
                Subject to the conditions below, you are granted a non-exclusive,
                worldwide, royalty-free permission to reproduce, share, translate,
                adapt and build upon material covered by this notice for non-commercial
                purposes.
              </p>
              <p>
                This permission applies only to rights that the owner owns or is
                authorised to license.
              </p>

              <h3>3. Conditions of reuse</h3>
              <p>
                Any use relying on the permission above must satisfy all of the
                following conditions:
              </p>
              <ul>
                <li>
                  Attribution: Clearly credit M. Young as the source,
                  identify the report by title, and provide a link to the original report
                  where reasonably practicable.
                </li>
                <li>
                  Changes: Clearly identify any material changes,
                  adaptations, abridgements or translations. Do not present modified
                  material as the unaltered original.
                </li>
                <li>
                  No implied endorsement: Do not imply that the owner
                  endorses you, your organisation, your work or your use of the material
                  without separate permission.
                </li>
                <li>
                  Third-party rights: Respect any separate copyright
                  notices, licence conditions or permissions applicable to third-party
                  material.
                </li>
              </ul>
              <p>
                Attribution must be reasonably prominent and appropriate to the medium
                in which the material is used.
              </p>

              <h3>4. Commercial use</h3>
              <p>The permission granted above does not authorise commercial use.</p>
              <p>
                Any commercial reproduction, distribution, publication, adaptation or
                other use of copyright-protected material covered by this notice requires
                prior written permission from the relevant rights holder, unless the use
                is otherwise permitted by applicable law.
              </p>
              <p>
                Commercial use includes use primarily intended to obtain commercial
                advantage or monetary compensation, including incorporation into
                commercial publications, products or services. This description is
                illustrative and is not exhaustive.
              </p>
              <p>
                Permission for commercial use may be granted on separate terms, including
                payment of a licensing fee.
              </p>

              <h3>5. Legal exceptions and limitations</h3>
              <p>
                Nothing in this notice is intended to restrict any use that is permitted
                without authorisation under applicable copyright law. This notice does
                not grant rights in material that the owner does not own or control.
              </p>

              <h3>6. Scope of permission</h3>
              <p>
                The permission granted in this notice is limited to the uses and
                conditions expressly stated above. All other rights in the protected
                material are reserved.
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
