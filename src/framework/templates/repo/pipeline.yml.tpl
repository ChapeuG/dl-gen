name: Pipeline-EngDados-Datalake
run-name: Pipeline-EngDados-Datalake-${{ github.ref_name }}

on:
  push:
    branches:
      - dev
      - qa
      - prd

env:
  ENGDADOS_REPO_URL: ${{ secrets.ENGDADOS_REPO_URL }}
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  ENGDADOS_REPO_NAME: ${GITHUB_REPOSITORY##*/}

jobs:
  deploy:
    runs-on:
      group: AWS-Data-DevopsShared

    steps:
      - name: Checkout code
        uses: actions/checkout@v3

      # - name: Setup SSH
      #   run: bash setup_ssh

      - name: Clone and Push Repository (dev)
        if: github.ref == 'refs/heads/dev'
        run: |
          bash setup_ssh
          git clone --mirror https://x-access-token:${GH_TOKEN}@github.com/${{ github.repository }} rtSync
          ls -l
          cd rtSync
          ls -l
          git branch -a
          git push --mirror codecommit::us-east-2://__CODECOMMIT_REPO__

      - name: Clone and Push Repository (qa)
        if: github.ref == 'refs/heads/qa'
        run: |
          bash setup_ssh
          git clone --mirror https://x-access-token:${GH_TOKEN}@github.com/${{ github.repository }} rtSync
          cd rtSync
          git branch -a
          git push --mirror codecommit::us-east-2://__CODECOMMIT_REPO__

      - name: Clone and Push Repository (prd)
        if: github.ref == 'refs/heads/prd'
        run: |
          bash setup_ssh
          git clone --mirror https://x-access-token:${GH_TOKEN}@github.com/${{ github.repository }} rtSync
          cd rtSync
          git branch -a
          git push --mirror codecommit::us-east-2://__CODECOMMIT_REPO__

      - name: Clean up workspace
        if: always()
        run: |
          echo "Limpando a workspace..."
          rm -rf $GITHUB_WORKSPACE/*
