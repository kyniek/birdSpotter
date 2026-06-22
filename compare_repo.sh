#!/bin/bash

# Skrypt do porównywania plików lokalnych ze zdalnym repozytorium
# Użycie: ./compare_repo.sh

REPO_URL="https://kyniek:XXX@github.com/kyniek/birdSpotter.git"
BRANCH="main"  # lub "master" - zmień jeśli potrzebujesz

echo "========================================="
echo "PORÓWNYWANIE REPOZYTORIUM"
echo "========================================="

# 1. Pobierz najnowszy stan zdalnego repozytorium
echo "📥 Pobieram najnowszy stan zdalnego repozytorium..."
git fetch $REPO_URL $BRANCH 2>/dev/null || git fetch origin $BRANCH

# 2. Znajdź nazwę zdalnej gałęzi
if git rev-parse --verify FETCH_HEAD >/dev/null 2>&1; then
    REMOTE_REF="FETCH_HEAD"
else
    REMOTE_REF="origin/$BRANCH"
fi

echo ""
echo "📊 PORÓWNANIE PLIKÓW ŚLEDZONYCH PRZEZ GIT"
echo "-----------------------------------------"

# 3. Porównaj pliki śledzone (zmodyfikowane w repo)
echo "Pliki zmodyfikowane w stosunku do zdalnego:"
git diff --name-only $REMOTE_REF -- 2>/dev/null

echo ""
echo "Statystyki zmian:"
git diff --stat $REMOTE_REF -- 2>/dev/null

echo ""
echo "📁 PLIKI NIEŚLEDZONE (nie dodane do repo)"
echo "-----------------------------------------"

# 4. Znajdź pliki nieśledzone (ignorując .git)
UNTRACKED_FILES=$(git ls-files --others --exclude-standard)

if [ -z "$UNTRACKED_FILES" ]; then
    echo "✅ Brak nieśledzonych plików"
else
    echo "Nieśledzone pliki:"
    echo "$UNTRACKED_FILES"

    echo ""
    echo "Szczegółowe porównanie nieśledzonych plików:"

    # Porównaj każdy nieśledzony plik z wersją zdalną (jeśli istnieje)
    for file in $UNTRACKED_FILES; do
        echo ""
        echo "📄 Plik: $file"

        # Sprawdź czy plik istnieje w zdalnym repo
        if git ls-tree -r $REMOTE_REF --name-only | grep -q "^$file$"; then
            echo "   ⚠️  Plik istnieje w zdalnym repo ale jest nieśledzony lokalnie!"
            echo "   Różnice:"
            git diff $REMOTE_REF -- "$file" 2>/dev/null | head -20
        else
            echo "   ✅ Nowy plik (nie istnieje w zdalnym repo)"
            echo "   Zawartość (pierwsze 10 linii):"
            if [ -f "$file" ]; then
                head -10 "$file" | sed 's/^/      /'
            fi
        fi
    done
fi

echo ""
echo "📂 PLIKI ZMIENIONE LOKALNIE (w tym nieśledzone)"
echo "-----------------------------------------"

# 5. Pokaż wszystkie pliki, które różnią się od zdalnych
echo "Wszystkie pliki różniące się od zdalnych:"

# Śledzone pliki z zmianami
TRACKED_CHANGED=$(git diff --name-only $REMOTE_REF -- 2>/dev/null)

# Nieśledzone pliki
UNTRACKED=$(git ls-files --others --exclude-standard)

# Połącz i posortuj
ALL_CHANGED=$(echo -e "$TRACKED_CHANGED\n$UNTRACKED" | sort -u | grep -v '^$')

if [ -z "$ALL_CHANGED" ]; then
    echo "✅ Wszystkie pliki są zgodne ze zdalnym repozytorium"
else
    echo "$ALL_CHANGED" | while read -r file; do
        if [ -n "$file" ]; then
            if echo "$TRACKED_CHANGED" | grep -q "^$file$"; then
                echo "   [ZMODYFIKOWANY] $file"
            else
                echo "   [NOWY/NIEŚLEDZONY] $file"
            fi
        fi
    done
fi

echo ""
echo "========================================="
echo "✅ Porównanie zakończone"
echo "========================================="

# 6. Opcjonalnie: zapisz szczegółowe różnice do pliku
echo ""
read -p "Czy chcesz zapisać szczegółowe różnice do pliku diff_output.txt? (t/n): " SAVE_DIFF
if [[ $SAVE_DIFF == "t" || $SAVE_DIFF == "T" ]]; then
    git diff $REMOTE_REF -- > diff_output.txt 2>/dev/null
    echo "📄 Szczegółowe różnice zapisane w diff_output.txt"

    # Dodaj też nieśledzone pliki
    echo "" >> diff_output.txt
    echo "===== NIEŚLEDZONE PLIKI =====" >> diff_output.txt
    git ls-files --others --exclude-standard >> diff_output.txt 2>/dev/null
    echo "✅ Zapisano!"
fi