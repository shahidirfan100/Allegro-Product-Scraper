FROM apify/actor-python-playwright:3.14

COPY --chown=myuser:myuser requirements.txt ./
# Scrapling drives Patchright, which ships its own patched Chromium. Installing it
# here keeps the stealth profile available inside the image.
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m patchright install --no-progress chromium

COPY --chown=myuser:myuser . ./
RUN python -m compileall -q src/

CMD ["python", "-m", "src"]
